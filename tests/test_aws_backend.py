"""Milestone 4: the same API on S3 + DynamoDB (SK-21, SK-22, SK-26).

Runs against moto, a local stand-in for AWS, so CI needs no account and no credentials. The
DynamoDB table is created from infra/template.yaml, so the code and the template cannot drift.
moto does not check pre-signed URL signatures or expiry: those are checked on real AWS in
docs/aws/deploy-m4.md (step 6).
"""

import dataclasses
import json
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import yaml
from conftest import STARTED_AT
from fastapi.testclient import TestClient

moto_server = pytest.importorskip("moto.server")
boto3 = pytest.importorskip("boto3")

from stresskit_api import create_app, processing  # noqa: E402
from stresskit_api.models import UploadStatus  # noqa: E402
from stresskit_api.settings import Settings  # noqa: E402
from stresskit_sdk import StressKitClient  # noqa: E402
from stresskit_sim import generate  # noqa: E402

REGION = "ap-southeast-7"
TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "template.yaml"
# Test-only secrets, stored in (moto) SSM the way a real deploy stores its own.
JWT_KEY = "fake-jwt-signing-key-for-tests-only-0000"
CLIENTS = {
    "clinic-a": {"secret": "fake-secret-a", "tenant_id": "tenant-clinic-a"},
    "clinic-b": {"secret": "fake-secret-b", "tenant_id": "tenant-clinic-b"},
}


def put_secrets(prefix, jwt_key=JWT_KEY, clients=CLIENTS) -> None:
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name=f"{prefix}/jwt-secret", Value=jwt_key, Type="SecureString")
    ssm.put_parameter(Name=f"{prefix}/clients", Value=json.dumps(clients), Type="SecureString")


@pytest.fixture(scope="session")
def aws_endpoint():
    server = moto_server.ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def aws(aws_endpoint, monkeypatch):
    """A fresh bucket, table and set of SSM secrets for each test. All values are fake."""
    monkeypatch.setenv("AWS_ENDPOINT_URL", aws_endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-test-secret")
    monkeypatch.setenv("AWS_REGION", REGION)
    bucket, table = f"stresskit-test-{uuid.uuid4().hex[:12]}", f"t-{uuid.uuid4().hex[:12]}"
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    spec = yaml.safe_load(TEMPLATE.read_text())["Resources"]["Table"]["Properties"]
    boto3.client("dynamodb", region_name=REGION).create_table(
        TableName=table,
        BillingMode=spec["BillingMode"],
        KeySchema=spec["KeySchema"],
        AttributeDefinitions=spec["AttributeDefinitions"],
    )
    prefix = f"/stresskit/test-{uuid.uuid4().hex[:8]}"
    put_secrets(prefix)
    monkeypatch.setenv("STRESSKIT_SSM_PREFIX", prefix)
    return {"bucket": bucket, "table": table, "prefix": prefix}


def aws_settings(aws, **changes) -> Settings:
    base = Settings.from_env()
    return dataclasses.replace(
        base, backend="aws", bucket=aws["bucket"], table=aws["table"], **changes
    )


@pytest.fixture
def aws_app(aws):
    return create_app(aws_settings(aws))


@pytest.fixture
def api(aws_app):
    with TestClient(aws_app) as client:
        yield client


def upload_and_wait(sdk, recording) -> dict:
    sent = sdk.upload_recording("watch-001", recording, STARTED_AT)
    return sdk.wait_until_processed(sent["upload_id"])


def sdk_for(api, client_id="clinic-a", secret="fake-secret-a") -> StressKitClient:
    # The API calls go to the test app; the file goes over real HTTP to the (moto) S3 URL.
    return StressKitClient(
        "http://testserver", client_id, secret, http=api, upload_http=httpx.Client(trust_env=False)
    )


@pytest.fixture
def sdk(api):
    return sdk_for(api)


def table_items(aws) -> list[dict]:
    return boto3.resource("dynamodb", region_name=REGION).Table(aws["table"]).scan()["Items"]


def s3_keys(aws) -> list[str]:
    resp = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=aws["bucket"])
    return [o["Key"] for o in resp.get("Contents", [])]


# --- SK-21 / SK-22: the whole flow on S3 and DynamoDB --------------------------------------


def test_sdk_end_to_end_on_s3_and_dynamodb(sdk, aws):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    done = upload_and_wait(sdk, generate("stressed", minutes=3, seed=2))
    assert done["status"] == "processed" and done["window_count"] == 3
    assert len(sdk.get_results("watch-001")) == 3
    assert s3_keys(aws) == [f"tenant-clinic-a/watch-001/{done['upload_id']}.json"]


def test_upload_link_is_s3_scoped_to_one_file_and_short_lived(sdk, aws):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    ticket = sdk.create_upload("watch-001", started_at=STARTED_AT, sample_rate_hz=25, duration_s=60)
    url = urlparse(ticket["upload_url"])
    query = parse_qs(url.query)
    assert url.path == f"/{aws['bucket']}/tenant-clinic-a/watch-001/{ticket['upload_id']}.json"
    assert query["X-Amz-Expires"] == ["900"]
    assert "content-type" in query["X-Amz-SignedHeaders"][0]  # only JSON can be sent
    assert "Authorization" not in ticket["upload_url"]


def test_complete_before_the_file_is_in_s3_is_409(sdk, api):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    ticket = sdk.create_upload("watch-001", started_at=STARTED_AT, sample_rate_hz=25, duration_s=60)
    resp = api.post(f"/v1/uploads/{ticket['upload_id']}/complete", headers=sdk._bearer())
    assert resp.status_code == 409


def test_local_blob_route_is_off_on_aws(api):
    resp = api.put("/v1/blobs/t/d/u.json?expires=1&signature=x", content=b"{}")
    assert resp.status_code == 404


def test_firmware_update_is_stored_in_dynamodb(sdk):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    sdk.update_device("watch-001", firmware_version="1.1")
    assert sdk.get_device("watch-001")["firmware_version"] == "1.1"


# --- SK-22 / SK-23: tenant isolation in the data model -------------------------------------


def test_other_tenant_cannot_see_device_upload_or_results(sdk, api, aws):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    done = upload_and_wait(sdk, generate("calm", minutes=1, seed=3))
    other = sdk_for(api, "clinic-b", "fake-secret-b")
    headers = other._bearer()
    assert api.get("/v1/devices/watch-001", headers=headers).status_code == 404
    assert api.get(f"/v1/uploads/{done['upload_id']}", headers=headers).status_code == 404
    assert api.get("/v1/results?device_id=watch-001", headers=headers).status_code == 404
    # Same device id in tenant B is a different device, not a clash.
    assert other.register_device("watch-001", model="S1", firmware_version="9")["device_id"]


def test_every_item_is_keyed_by_tenant(sdk, aws):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    upload_and_wait(sdk, generate("calm", minutes=2, seed=4))
    items = table_items(aws)
    assert items and all(i["PK"].startswith("TENANT#tenant-clinic-a#") for i in items)


def test_reprocessing_overwrites_results_in_dynamodb(aws_app, sdk):  # SK-11 on AWS
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    done = upload_and_wait(sdk, generate("calm", minutes=2, seed=5))
    store, blobs = aws_app.state.store, aws_app.state.blobs
    upload = store.get_upload("tenant-clinic-a", done["upload_id"])
    store.put_upload("tenant-clinic-a", upload.model_copy(update={"status": "processing"}))
    processing.process_upload(store, blobs, "tenant-clinic-a", done["upload_id"])
    assert len(sdk.get_results("watch-001")) == 2


def test_results_limit_returns_the_latest_windows_oldest_first(sdk):
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    upload_and_wait(sdk, generate("calm", minutes=4, seed=6))
    items = sdk.get_results("watch-001", limit=2)
    starts = [i["window_start"] for i in items]
    assert len(items) == 2 and starts == sorted(starts)
    assert starts[-1] == sdk.get_results("watch-001")[-1]["window_start"]


# --- SK-18 on AWS: idempotency keys live 24 hours ------------------------------------------


def test_idempotency_key_replays_then_expires(sdk, aws):
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    args = dict(started_at=STARTED_AT, sample_rate_hz=25, duration_s=60, idempotency_key="k-1")
    first = sdk.create_upload("watch-001", **args)
    assert sdk.create_upload("watch-001", **args)["upload_id"] == first["upload_id"]

    idem = [i for i in table_items(aws) if "#IDEM#" in i["PK"]]
    assert len(idem) == 1 and int(idem[0]["expires_at"]) > time.time() + 23 * 3600
    # Pretend a day has passed. DynamoDB removes expired items lazily, so the API must
    # ignore an expired record itself.
    table = boto3.resource("dynamodb", region_name=REGION).Table(aws["table"])
    table.update_item(
        Key={"PK": idem[0]["PK"], "SK": "META"},
        UpdateExpression="SET expires_at = :past",
        ExpressionAttributeValues={":past": int(time.time()) - 1},
    )
    assert sdk.create_upload("watch-001", **args)["upload_id"] != first["upload_id"]


def test_racing_requests_with_one_key_get_one_upload(aws_app, sdk, monkeypatch):
    # Two requests with the same key both pass the "seen it?" check before either stores.
    sdk.register_device("watch-001", model="S1", firmware_version="1")
    args = dict(started_at=STARTED_AT, sample_rate_hz=25, duration_s=60, idempotency_key="k-r")
    first = sdk.create_upload("watch-001", **args)
    monkeypatch.setattr(aws_app.state.store, "get_idempotent", lambda *a: None)
    assert sdk.create_upload("watch-001", **args)["upload_id"] == first["upload_id"]


# --- SK-23 / SK-26: secrets from SSM, size limit enforced by the worker --------------------


def test_secrets_are_read_from_ssm(aws, api):
    settings = Settings.from_env()
    assert settings.jwt_secret == JWT_KEY and sorted(settings.clients) == ["clinic-a", "clinic-b"]
    ok = {"grant_type": "client_credentials", "client_id": "clinic-a"}
    assert api.post("/v1/oauth/token", data=ok | {"client_secret": "fake-secret-a"}).is_success
    demo = ok | {"client_id": "demo-clinic-a", "client_secret": "demo-secret-a"}
    assert api.post("/v1/oauth/token", data=demo).status_code == 401


def test_aws_refuses_to_start_without_ssm(aws, monkeypatch):
    # A forgotten STRESSKIT_SSM_PREFIX would mean signing tokens with the public demo key.
    monkeypatch.delenv("STRESSKIT_SSM_PREFIX")
    with pytest.raises(RuntimeError, match="STRESSKIT_SSM_PREFIX"):
        create_app(aws_settings(aws))


def test_aws_refuses_the_public_demo_secrets_even_from_ssm(aws, monkeypatch):
    prefix = f"/stresskit/test-{uuid.uuid4().hex[:8]}"
    put_secrets(prefix, clients={"demo-clinic-a": {"secret": "demo-secret-a", "tenant_id": "t"}})
    monkeypatch.setenv("STRESSKIT_SSM_PREFIX", prefix)
    with pytest.raises(RuntimeError, match="demo secrets"):
        create_app(aws_settings(aws))


def test_missing_ssm_parameters_fail_at_startup(aws, monkeypatch):
    monkeypatch.setenv("STRESSKIT_SSM_PREFIX", "/stresskit/does-not-exist")
    with pytest.raises(RuntimeError, match="Missing SSM parameters"):
        Settings.from_env()


def test_oversize_file_in_s3_is_marked_failed(aws):
    # S3 pre-signed PUT URLs cannot cap the size, so the worker checks it before reading.
    with TestClient(create_app(aws_settings(aws, max_upload_bytes=10_000))) as api:
        sdk = sdk_for(api)
        sdk.register_device("watch-001", model="S1", firmware_version="1")
        done = upload_and_wait(sdk, generate("calm", minutes=1, seed=7))
    assert done["status"] == UploadStatus.failed
    assert "larger than" in done["error"]
