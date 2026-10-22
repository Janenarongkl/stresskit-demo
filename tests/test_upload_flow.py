from collections import Counter
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import STARTED_AT

from stresskit_sdk import StressKitError
from stresskit_sim import generate

DEVICE = {"device_id": "watch-001", "model": "StressBand S1", "firmware_version": "1.4.2"}
UPLOAD = {
    "device_id": "watch-001",
    "started_at": STARTED_AT.isoformat(),
    "sample_rate_hz": 25,
    "duration_s": 120,
}


@pytest.mark.parametrize(
    ("scenario", "label", "quality"),
    [
        ("calm", "not_stressed", "good"),
        ("stressed", "stressed", "good"),
        ("moving", "na", "motion"),
    ],
)
def test_end_to_end_with_sdk(sdk, scenario, label, quality):
    sdk.register_device("watch-001", model="StressBand S1", firmware_version="1.4.2")
    done = sdk.upload_recording("watch-001", generate(scenario, minutes=2, seed=1), STARTED_AT)
    assert done["status"] == "processing"

    upload = sdk.wait_until_processed(done["upload_id"])
    assert upload["status"] == "processed"
    assert upload["window_count"] == 2

    results = sdk.get_results("watch-001")
    assert [r["label"] for r in results] == [label, label]
    assert {r["signal_quality"] for r in results} == {quality}
    assert results[0]["window_start"].startswith("2026-10-21T09:00:00")
    assert results[1]["window_start"].startswith("2026-10-21T09:01:00")


def test_duplicate_device_is_409(http, auth_a):
    assert http.post("/v1/devices", json=DEVICE, headers=auth_a).status_code == 201
    assert http.post("/v1/devices", json=DEVICE, headers=auth_a).status_code == 409


def test_bad_device_id_is_422_problem(http, auth_a):
    resp = http.post("/v1/devices", json={**DEVICE, "device_id": "../etc"}, headers=auth_a)
    assert resp.status_code == 422
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["errors"][0]["loc"] == ["body", "device_id"]


def test_idempotency_key_replays_same_upload(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    headers = {**auth_a, "Idempotency-Key": "k-123"}
    first = http.post("/v1/uploads", json=UPLOAD, headers=headers)
    second = http.post("/v1/uploads", json=UPLOAD, headers=headers)
    assert first.status_code == second.status_code == 201
    assert second.headers["idempotent-replayed"] == "true"
    assert first.json()["upload_id"] == second.json()["upload_id"]


def test_idempotency_key_with_different_body_is_409(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    headers = {**auth_a, "Idempotency-Key": "k-123"}
    http.post("/v1/uploads", json=UPLOAD, headers=headers)
    resp = http.post("/v1/uploads", json={**UPLOAD, "duration_s": 180}, headers=headers)
    assert resp.status_code == 409


def test_complete_before_file_is_409(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    upload_id = http.post("/v1/uploads", json=UPLOAD, headers=auth_a).json()["upload_id"]
    resp = http.post(f"/v1/uploads/{upload_id}/complete", headers=auth_a)
    assert resp.status_code == 409


def test_tampered_or_expired_upload_url_is_403(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    url = http.post("/v1/uploads", json=UPLOAD, headers=auth_a).json()["upload_url"]
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    tampered = url.replace(query["signature"][0], "0" * 64)
    assert http.put(tampered, content=b"{}").status_code == 403

    later = url.replace(f"expires={query['expires'][0]}", f"expires={int(query['expires'][0]) + 1}")
    assert http.put(later, content=b"{}").status_code == 403

    other_key = url.replace("watch-001", "watch-002")
    assert http.put(other_key, content=b"{}").status_code == 403


def test_bad_file_marks_upload_failed(sdk, http):
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    ticket = sdk.create_upload("watch-001", started_at=STARTED_AT, sample_rate_hz=25, duration_s=60)
    sdk.put_file(ticket["upload_url"], {"ppg": [1, 2, 3], "acc": [[0, 0, 1]]})
    sdk.complete_upload(ticket["upload_id"])
    upload = sdk.wait_until_processed(ticket["upload_id"])
    assert upload["status"] == "failed"
    assert "same length" in upload["error"]


def test_sdk_raises_problem_details(sdk):
    with pytest.raises(StressKitError) as err:
        sdk.get_device("nope")
    assert err.value.status == 404
    assert err.value.problem["title"] == "Not Found"


def test_tenant_isolation(http, auth_a, auth_b, sdk):
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    done = sdk.upload_recording("watch-001", generate("calm", minutes=1, seed=2), STARTED_AT)

    # Clinic B uses the same ids and sees nothing of clinic A's data.
    assert http.get("/v1/devices/watch-001", headers=auth_b).status_code == 404
    assert http.get(f"/v1/uploads/{done['upload_id']}", headers=auth_b).status_code == 404
    assert (
        http.get("/v1/results", params={"device_id": "watch-001"}, headers=auth_b).status_code
        == 404
    )

    # Clinic B can register its own watch-001 without touching clinic A's.
    assert http.post("/v1/devices", json=DEVICE, headers=auth_b).status_code == 201
    labels = Counter(r["label"] for r in sdk.get_results("watch-001"))
    assert labels == {"not_stressed": 1}
