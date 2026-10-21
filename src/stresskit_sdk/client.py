from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


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
    ) -> None:
        self._http = http or httpx.Client(base_url=base_url, timeout=30)
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
            return resp.json()
        try:
            problem = resp.json()
        except ValueError:
            problem = {"title": resp.reason_phrase, "detail": resp.text}
        raise StressKitError(resp.status_code, problem)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Authenticated request with retries on network errors and 429/5xx."""
        extra_headers = kwargs.pop("headers", {})
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._http.request(
                    method, url, headers={**self._bearer(), **extra_headers}, **kwargs
                )
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
            else:
                if resp.status_code not in RETRY_STATUSES or attempt == self._max_retries:
                    return self._check(resp)
            time.sleep(min(0.5 * 2**attempt, 5))

    # --- API ------------------------------------------------------------------------------

    def register_device(self, device_id: str, *, model: str, firmware_version: str) -> dict:
        return self._request(
            "POST",
            "/v1/devices",
            json={"device_id": device_id, "model": model, "firmware_version": firmware_version},
        )

    def get_device(self, device_id: str) -> dict:
        return self._request("GET", f"/v1/devices/{device_id}")

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
        resp = self._http.put(
            upload_url,
            content=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        self._check(resp)

    def complete_upload(self, upload_id: str) -> dict:
        return self._request("POST", f"/v1/uploads/{upload_id}/complete")

    def upload_recording(self, device_id: str, recording: Any, started_at: datetime) -> dict:
        """The whole upload: ask for a URL, PUT the file, tell the API it is there."""
        ticket = self.create_upload(
            device_id,
            started_at=started_at,
            sample_rate_hz=recording.sample_rate_hz,
            duration_s=recording.duration_s,
        )
        self.put_file(ticket["upload_url"], recording.to_json())
        return self.complete_upload(ticket["upload_id"])

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
