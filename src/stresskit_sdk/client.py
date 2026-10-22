from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

from .offline import OfflineQueue

RETRY_STATUSES = {429, 500, 502, 503, 504}
# While draining the queue these stop the drain and keep the recording queued: a bad or
# rotated secret (401) or a refused link (403) is fixed by the customer, not by giving up.
KEEP_QUEUED_STATUSES = RETRY_STATUSES | {401, 403}
MAX_RETRY_AFTER_S = 60


class StressKitError(Exception):
    """An error response from the API, carrying its problem+json body."""

    def __init__(self, status: int, problem: dict[str, Any]):
        self.status = status
        self.problem = problem
        super().__init__(f"{status} {problem.get('title', '')}: {problem.get('detail', '')}")


class StressKitClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.Client | None = None,
        max_retries: int = 3,
        offline_queue: OfflineQueue | None = None,
        upload_http: httpx.Client | None = None,
    ) -> None:
        self._http = http or httpx.Client(base_url=base_url, timeout=30)
        # The file goes to the upload URL's own host (S3 on AWS), not the API.
        self._upload_http = upload_http or self._http
        self.offline_queue = offline_queue
        self._client_id = client_id
        self._client_secret = client_secret
        self._max_retries = max_retries
        self._token: str | None = None
        self._token_expires_at = 0.0

    # --- auth -----------------------------------------------------------------------------

    def _bearer(self) -> dict[str, str]:
        # Refresh a minute early so a token never expires mid-request.
        if self._token is None or time.time() > self._token_expires_at - 60:
            resp = self._http.post(
                "/v1/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            body = self._check(resp)
            self._token = body["access_token"]
            self._token_expires_at = time.time() + body["expires_in"]
        return {"Authorization": f"Bearer {self._token}"}

    # --- plumbing -------------------------------------------------------------------------

    @staticmethod
    def _check(resp: httpx.Response) -> Any:
        if resp.is_success:
            return resp.json() if resp.content else {}  # S3 answers a PUT with an empty body
        try:
            problem = resp.json()
        except ValueError:
            problem = {"title": resp.reason_phrase, "detail": resp.text}
        raise StressKitError(resp.status_code, problem)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Authenticated request with retries on network errors and 429/5xx.

        A 401 on a cached token (for example, revoked, or the phone's clock was wrong) gets one
        fresh token and one more try. Other 4xx answers are never retried.
        """
        extra_headers = kwargs.pop("headers", {})
        refreshed = False
        attempt = 0
        while True:
            try:
                resp = self._http.request(
                    method, url, headers={**self._bearer(), **extra_headers}, **kwargs
                )
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
                resp = None
            else:
                if resp.status_code == 401 and not refreshed:
                    refreshed, self._token = True, None
                    continue
                if resp.status_code not in RETRY_STATUSES or attempt == self._max_retries:
                    return self._check(resp)
            time.sleep(self._retry_delay(attempt, resp))
            attempt += 1

    @staticmethod
    def _retry_delay(attempt: int, resp: httpx.Response | None) -> float:
        """Exponential back-off, or longer if the server asked for it with Retry-After."""
        delay = min(0.5 * 2**attempt, 5)
        retry_after = resp.headers.get("Retry-After") if resp is not None else None
        if retry_after and retry_after.isdigit():
            delay = max(delay, min(int(retry_after), MAX_RETRY_AFTER_S))
        return delay

    # --- API ------------------------------------------------------------------------------

    def register_device(self, device_id: str, *, model: str, firmware_version: str) -> dict:
        return self._request(
            "POST",
            "/v1/devices",
            json={"device_id": device_id, "model": model, "firmware_version": firmware_version},
        )

    def get_device(self, device_id: str) -> dict:
        return self._request("GET", f"/v1/devices/{device_id}")

    def update_device(self, device_id: str, *, firmware_version: str) -> dict:
        """Record a firmware upgrade. Uploads made before it keep the old version."""
        return self._request(
            "PATCH", f"/v1/devices/{device_id}", json={"firmware_version": firmware_version}
        )

    def create_upload(
        self,
        device_id: str,
        *,
        started_at: datetime,
        sample_rate_hz: int,
        duration_s: int,
        idempotency_key: str | None = None,
    ) -> dict:
        return self._request(
            "POST",
            "/v1/uploads",
            json={
                "device_id": device_id,
                "started_at": started_at.isoformat(),
                "sample_rate_hz": sample_rate_hz,
                "duration_s": duration_s,
            },
            # One key per logical upload: a retry after a timeout returns the same upload.
            headers={"Idempotency-Key": idempotency_key or str(uuid.uuid4())},
        )

    def put_file(self, upload_url: str, payload: dict) -> None:
        # No Authorization header: the signature in the URL is the permission.
        resp = self._upload_http.put(
            upload_url,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        self._check(resp)

    def complete_upload(self, upload_id: str) -> dict:
        return self._request("POST", f"/v1/uploads/{upload_id}/complete")

    def upload_recording(self, device_id: str, recording: Any, started_at: datetime) -> dict:
        """The whole upload: ask for a URL, PUT the file, tell the API it is there.

        With an offline queue, a network failure (after retries) or a server that stays
        unavailable queues the recording instead of raising, and returns
        {"status": "queued", "queue_id": ...}. Call drain_queue() when the network is back.
        """
        item = {
            "device_id": device_id,
            "started_at": started_at.isoformat(),
            "sample_rate_hz": recording.sample_rate_hz,
            "duration_s": recording.duration_s,
            "idempotency_key": str(uuid.uuid4()),
            "payload": recording.to_json(),
        }
        try:
            return self._send(item)
        except (httpx.TransportError, StressKitError) as exc:
            retryable = isinstance(exc, httpx.TransportError) or exc.status in RETRY_STATUSES
            if self.offline_queue is None or not retryable:
                raise
            return {"status": "queued", "queue_id": self.offline_queue.add(item)}

    def drain_queue(self) -> dict:
        """Send queued recordings, oldest first.

        Stops at the first network failure, server error or authentication failure, and keeps
        the rest queued; "stopped" in the result says why. Only recordings the server refuses
        for good (for example, an unknown device) are set aside in failed/, so they don't
        block the rest.
        """
        if self.offline_queue is None:
            raise ValueError("This client has no offline queue.")
        sent, failed, stopped = [], [], None
        for queue_id, item in self.offline_queue.items():
            try:
                sent.append(self._send(item))
            except httpx.TransportError as exc:
                stopped = f"network: {exc}"
                break
            except StressKitError as exc:
                if exc.status in KEEP_QUEUED_STATUSES:
                    stopped = str(exc)
                    break
                self.offline_queue.set_aside(queue_id, str(exc))
                failed.append({"queue_id": queue_id, "error": str(exc)})
                continue
            self.offline_queue.remove(queue_id)
        remaining = len(self.offline_queue)
        return {"sent": sent, "failed": failed, "remaining": remaining, "stopped": stopped}

    def _send(self, item: dict) -> dict:
        def ticket() -> dict:
            return self.create_upload(
                item["device_id"],
                started_at=datetime.fromisoformat(item["started_at"]),
                sample_rate_hz=item["sample_rate_hz"],
                duration_s=item["duration_s"],
                idempotency_key=item["idempotency_key"],
            )

        upload = ticket()
        if upload["status"] == "pending_upload":
            try:
                self.put_file(upload["upload_url"], item["payload"])
            except StressKitError as exc:
                if exc.status != 403:
                    raise
                # The link expired between asking and sending: the same key gives a fresh one.
                upload = ticket()
                self.put_file(upload["upload_url"], item["payload"])
        return self.complete_upload(upload["upload_id"])

    def get_upload(self, upload_id: str) -> dict:
        return self._request("GET", f"/v1/uploads/{upload_id}")

    def wait_until_processed(self, upload_id: str, timeout_s: float = 30) -> dict:
        deadline = time.time() + timeout_s
        while True:
            upload = self.get_upload(upload_id)
            if upload["status"] in ("processed", "failed") or time.time() > deadline:
                return upload
            time.sleep(0.5)

    def get_results(self, device_id: str, limit: int = 100) -> list[dict]:
        return self._request("GET", "/v1/results", params={"device_id": device_id, "limit": limit})[
            "items"
        ]
