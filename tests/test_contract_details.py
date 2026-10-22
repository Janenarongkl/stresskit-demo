"""Smaller contract rules that backlog acceptance criteria rely on (docs/product/backlog.md)."""

import dataclasses
import time
from datetime import UTC, datetime

import httpx
import pytest
from conftest import STARTED_AT, token_for
from fastapi.testclient import TestClient

from stresskit_api import create_app, main, mock_model, processing
from stresskit_api.models import UploadStatus
from stresskit_api.settings import Settings
from stresskit_sdk import StressKitClient, StressKitError
from stresskit_sim import generate

DEVICE = {"device_id": "watch-001", "model": "StressBand S1", "firmware_version": "1.4.2"}
UPLOAD = {
    "device_id": "watch-001",
    "started_at": STARTED_AT.isoformat(),
    "sample_rate_hz": 25,
    "duration_s": 120,
}


def test_upload_url_is_for_one_file_and_expires_in_15_minutes(http, auth_a):  # SK-6
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    ticket = http.post("/v1/uploads", json=UPLOAD, headers=auth_a).json()
    assert (
        f"/v1/blobs/tenant-clinic-a/watch-001/{ticket['upload_id']}.json?" in ticket["upload_url"]
    )
    expires_at = datetime.fromisoformat(ticket["upload_url_expires_at"])
    assert 890 <= (expires_at - datetime.now(UTC)).total_seconds() <= 900


def test_file_over_size_limit_is_413(tmp_path):  # SK-6
    settings = dataclasses.replace(Settings.from_env(), data_dir=tmp_path, max_upload_bytes=100)
    with TestClient(create_app(settings)) as http:
        auth = {"Authorization": f"Bearer {token_for(http)}"}
        http.post("/v1/devices", json=DEVICE, headers=auth)
        url = http.post("/v1/uploads", json=UPLOAD, headers=auth).json()["upload_url"]
        resp = http.put(url, content=b"x" * 101)
        assert resp.status_code == 413
        assert resp.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("duration_s", [59, 24 * 3600 + 1])
def test_duration_outside_one_minute_to_one_day_is_422(http, auth_a, duration_s):  # SK-6
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    resp = http.post("/v1/uploads", json={**UPLOAD, "duration_s": duration_s}, headers=auth_a)
    assert resp.status_code == 422


def test_idempotency_keys_are_per_tenant(http, auth_a, auth_b):  # SK-7
    for auth in (auth_a, auth_b):
        http.post("/v1/devices", json=DEVICE, headers=auth)
    a = http.post("/v1/uploads", json=UPLOAD, headers={**auth_a, "Idempotency-Key": "same"})
    b = http.post("/v1/uploads", json=UPLOAD, headers={**auth_b, "Idempotency-Key": "same"})
    assert a.status_code == b.status_code == 201
    assert "idempotent-replayed" not in b.headers
    assert a.json()["upload_id"] != b.json()["upload_id"]


def test_only_moving_minutes_are_na():  # SK-10
    calm, moving = generate("calm", minutes=1, seed=6), generate("moving", minutes=1, seed=6)
    out = mock_model.analyse(calm.ppg + moving.ppg, calm.acc + moving.acc, calm.sample_rate_hz)
    assert [w.label for w in out] == ["not_stressed", "na"]
    assert [w.signal_quality for w in out] == ["good", "motion"]


@pytest.mark.parametrize("limit", [0, 1441])
def test_results_limit_outside_1_to_1440_is_422(http, auth_a, limit):  # SK-9
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    params = {"device_id": "watch-001", "limit": limit}
    assert http.get("/v1/results", params=params, headers=auth_a).status_code == 422


def test_complete_twice_queues_processing_once(sdk, monkeypatch):  # SK-8
    calls = []
    real = main.process_upload
    monkeypatch.setattr(main, "process_upload", lambda *a: (calls.append(a), real(*a)))
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    first = sdk.upload_recording("watch-001", generate("calm", minutes=1, seed=4), STARTED_AT)
    again = sdk.complete_upload(first["upload_id"])
    assert again["upload_id"] == first["upload_id"]
    assert again["status"] == "processed"
    assert len(calls) == 1


def test_reprocessing_overwrites_results(app, sdk):  # SK-11
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    done = sdk.upload_recording("watch-001", generate("calm", minutes=2, seed=5), STARTED_AT)
    store, blobs = app.state.store, app.state.blobs
    upload = store.get_upload("tenant-clinic-a", done["upload_id"])
    store.put_upload(
        "tenant-clinic-a", upload.model_copy(update={"status": UploadStatus.processing})
    )
    processing.process_upload(store, blobs, "tenant-clinic-a", done["upload_id"])
    assert len(sdk.get_results("watch-001")) == 2


def test_sdk_reuses_token_and_refreshes_before_expiry(sdk, http, monkeypatch):  # SK-15
    token_calls = []
    real_post = http.post

    def counting_post(url, *args, **kwargs):
        if url == "/v1/oauth/token":
            token_calls.append(url)
        return real_post(url, *args, **kwargs)

    monkeypatch.setattr(http, "post", counting_post)
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    sdk.get_device("watch-001")
    assert len(token_calls) == 1

    sdk._token_expires_at = time.time() + 30  # less than a minute left
    sdk.get_device("watch-001")
    assert len(token_calls) == 2


def _flaky_client(failures: int, monkeypatch) -> tuple[StressKitClient, list[int]]:
    """An SDK whose server answers 503 `failures` times before succeeding."""
    monkeypatch.setattr("stresskit_sdk.client.time.sleep", lambda s: None)
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        attempts.append(1)
        if len(attempts) <= failures:
            problem = {"title": "Service Unavailable", "status": 503, "detail": "Try again."}
            return httpx.Response(503, json=problem)
        return httpx.Response(200, json={"device_id": "watch-001"})

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://mock")
    return StressKitClient("http://mock", "id", "secret", http=http), attempts


def test_sdk_retries_server_errors_then_succeeds(monkeypatch):  # SK-15
    client, attempts = _flaky_client(2, monkeypatch)
    assert client.get_device("watch-001") == {"device_id": "watch-001"}
    assert len(attempts) == 3


def test_sdk_gives_up_after_three_retries(monkeypatch):  # SK-15
    client, attempts = _flaky_client(10, monkeypatch)
    with pytest.raises(StressKitError) as err:
        client.get_device("watch-001")
    assert err.value.status == 503
    assert len(attempts) == 4
