"""End-to-end walkthrough of StressKit, printing every HTTP call.

    python scripts/demo.py                                  # in-process, no server needed
    python scripts/demo.py --base-url http://127.0.0.1:8000 # against a running server
    python scripts/demo.py --base-url ... --client a-id:a-secret --other-client b-id:b-secret

Steps: get a token, register a watch, upload three recordings (calm, stressed, moving),
read the results, then show a retry with the same Idempotency-Key, a call without a token,
and another clinic trying to read this clinic's data.
"""

import argparse
import dataclasses
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stresskit_sdk import StressKitClient, StressKitError  # noqa: E402
from stresskit_sim import generate  # noqa: E402

CLIENT_A = ("demo-clinic-a", "demo-secret-a")
CLIENT_B = ("demo-clinic-b", "demo-secret-b")


def log_request(request: httpx.Request) -> None:
    path = request.url.path + (
        f"?{request.url.query.decode()[:40]}..." if request.url.query else ""
    )
    auth = " [Bearer]" if "authorization" in request.headers else ""
    idem = (
        f" [Idempotency-Key {request.headers['idempotency-key'][:8]}]"
        if ("idempotency-key" in request.headers)
        else ""
    )
    print(f"  -> {request.method} {path}{auth}{idem}")


def log_response(response: httpx.Response) -> None:
    replay = " (replayed)" if response.headers.get("idempotent-replayed") else ""
    print(f"  <- {response.status_code} {response.reason_phrase}{replay}")


def make_http(base_url: str | None) -> httpx.Client:
    hooks = {"request": [log_request], "response": [log_response]}
    if base_url:
        return httpx.Client(base_url=base_url, timeout=30, event_hooks=hooks)
    from fastapi.testclient import TestClient

    from stresskit_api import create_app
    from stresskit_api.settings import Settings

    settings = dataclasses.replace(Settings.from_env(), data_dir=Path(tempfile.mkdtemp()))
    client = TestClient(create_app(settings), base_url="http://testserver")
    client.event_hooks = hooks
    return client


def step(title: str) -> None:
    print(f"\n== {title}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", help="Running API, e.g. http://127.0.0.1:8000")
    parser.add_argument("--client", default=":".join(CLIENT_A), help="client_id:client_secret")
    parser.add_argument(
        "--other-client", default=":".join(CLIENT_B), help="A second tenant, for step 8"
    )
    args = parser.parse_args()
    http = make_http(args.base_url)
    base = args.base_url or "http://testserver"
    clinic_a = StressKitClient(base, *args.client.split(":", 1), http=http)
    device_id = f"watch-{uuid.uuid4().hex[:6]}"

    step(f"1. Clinic A gets a token and registers {device_id}")
    clinic_a.register_device(device_id, model="StressBand S1", firmware_version="1.4.2")

    start = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=1)
    for n, scenario in enumerate(["calm", "stressed", "moving"]):
        step(f"{n + 2}. Upload a 2-minute '{scenario}' recording (ask for URL, PUT file, complete)")
        rec = generate(scenario, minutes=2, seed=n)
        done = clinic_a.upload_recording(device_id, rec, start + timedelta(minutes=2 * n))
        final = clinic_a.wait_until_processed(done["upload_id"])
        print(f"  upload {final['upload_id']}: {final['status']}, {final['window_count']} windows")

    step("5. Read results: one label per 60-second window")
    for r in clinic_a.get_results(device_id):
        hr = f"{r['heart_rate_bpm']:5.1f} bpm" if r["heart_rate_bpm"] else "   --    "
        print(f"  {r['window_start'][11:16]}  {r['label']:<13} {hr}  quality={r['signal_quality']}")

    step("6. Retry: same Idempotency-Key twice returns the same upload, not a duplicate")
    key = str(uuid.uuid4())
    kwargs = {"started_at": start, "sample_rate_hz": 25, "duration_s": 60, "idempotency_key": key}
    first = clinic_a.create_upload(device_id, **kwargs)
    second = clinic_a.create_upload(device_id, **kwargs)
    print(f"  same upload_id: {first['upload_id'] == second['upload_id']}")

    step("7. No token: the API refuses")
    http.get(f"/v1/devices/{device_id}")

    step("8. Clinic B asks for clinic A's device: 404, as if it does not exist")
    clinic_b = StressKitClient(base, *args.other_client.split(":", 1), http=http)
    try:
        clinic_b.get_device(device_id)
    except StressKitError as err:
        print(f"  SDK raised: {err}")

    print("\nDone. Open /docs on the running server to try the same calls in the browser.")


if __name__ == "__main__":
    main()
