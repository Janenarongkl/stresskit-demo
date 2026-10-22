"""SK-5: results can be traced to the firmware that recorded them."""

from conftest import STARTED_AT

DEVICE = {"device_id": "watch-001", "model": "StressBand S1", "firmware_version": "1.4.2"}
UPLOAD = {
    "device_id": "watch-001",
    "started_at": STARTED_AT.isoformat(),
    "sample_rate_hz": 25,
    "duration_s": 120,
}


def test_patch_records_a_firmware_upgrade(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    resp = http.patch("/v1/devices/watch-001", json={"firmware_version": "1.5.0"}, headers=auth_a)
    assert resp.status_code == 200
    assert resp.json()["firmware_version"] == "1.5.0"
    assert resp.json()["updated_at"] is not None
    assert http.get("/v1/devices/watch-001", headers=auth_a).json()["firmware_version"] == "1.5.0"


def test_uploads_keep_the_firmware_they_were_recorded_with(http, auth_a):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    before = http.post("/v1/uploads", json=UPLOAD, headers=auth_a).json()
    assert before["firmware_version"] == "1.4.2"

    http.patch("/v1/devices/watch-001", json={"firmware_version": "1.5.0"}, headers=auth_a)
    after = http.post("/v1/uploads", json=UPLOAD, headers=auth_a).json()
    assert after["firmware_version"] == "1.5.0"
    old = http.get(f"/v1/uploads/{before['upload_id']}", headers=auth_a).json()
    assert old["firmware_version"] == "1.4.2"


def test_patch_unknown_or_other_tenants_device_is_404(http, auth_a, auth_b):
    http.post("/v1/devices", json=DEVICE, headers=auth_a)
    body = {"firmware_version": "9.9.9"}
    assert http.patch("/v1/devices/watch-404", json=body, headers=auth_a).status_code == 404
    assert http.patch("/v1/devices/watch-001", json=body, headers=auth_b).status_code == 404
    assert http.get("/v1/devices/watch-001", headers=auth_a).json()["firmware_version"] == "1.4.2"


def test_result_leads_to_firmware_through_its_upload(sdk):
    from stresskit_sim import generate

    sdk.register_device("watch-001", model="S1", firmware_version="2.0.1")
    sdk.upload_recording("watch-001", generate("calm", minutes=1, seed=8), STARTED_AT)
    result = sdk.get_results("watch-001")[0]
    assert sdk.get_upload(result["upload_id"])["firmware_version"] == "2.0.1"
