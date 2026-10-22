"""Milestone 3: the SDK under bad networks (SK-17 offline queue, SK-18 retry safety)."""

import time
from datetime import timedelta

import httpx
import jwt
import pytest
from conftest import STARTED_AT

from stresskit_api import main
from stresskit_api.auth import AUDIENCE, ISSUER
from stresskit_api.settings import DEMO_JWT_SECRET
from stresskit_sdk import OfflineQueue, OfflineQueueFull, StressKitClient, StressKitError
from stresskit_sim import generate


class Network(httpx.BaseTransport):
    """Sits between the SDK and the test server and misbehaves on purpose."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.offline = False
        self.offline_methods: set[str] = set()  # e.g. {"PUT"}: only the file upload fails
        self.drop_reply_to: dict[tuple[str, str], int] = {}  # (method, path suffix) -> times

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.offline or request.method in self.offline_methods:
            raise httpx.ConnectError("no network", request=request)
        inner = self.inner.handle_request(request)
        resp = httpx.Response(inner.status_code, headers=inner.headers, content=inner.read())
        for (method, suffix), times in self.drop_reply_to.items():
            if times and request.method == method and request.url.path.endswith(suffix):
                # The server did the work, but the phone never hears back.
                self.drop_reply_to[(method, suffix)] = times - 1
                raise httpx.ReadTimeout("reply lost", request=request)
        return resp


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr("stresskit_sdk.client.time.sleep", lambda s: None)


@pytest.fixture
def net(http):
    return Network(http._transport)


def client_on(net, queue=None) -> StressKitClient:
    http = httpx.Client(transport=net, base_url="http://testserver")
    return StressKitClient(
        "http://testserver", "demo-clinic-a", "demo-secret-a", http=http, offline_queue=queue
    )


def uploads_in(app) -> list:
    return list(app.state.store._uploads.values())


def recording(minutes=1, seed=1):
    return generate("calm", minutes=minutes, seed=seed)


# --- SK-18: retries never duplicate --------------------------------------------------------


def test_lost_reply_to_create_upload_gives_one_upload(app, net):
    sdk = client_on(net)
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.drop_reply_to[("POST", "/v1/uploads")] = 1
    done = sdk.upload_recording("watch-001", recording(), STARTED_AT)
    assert [u.upload_id for u in uploads_in(app)] == [done["upload_id"]]


def test_network_error_on_complete_queues_processing_once(net, monkeypatch):
    calls = []
    real = main.process_upload
    monkeypatch.setattr(main, "process_upload", lambda *a: (calls.append(a), real(*a)))
    sdk = client_on(net)
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.drop_reply_to[("POST", "/complete")] = 1
    sdk.upload_recording("watch-001", recording(), STARTED_AT)
    assert len(calls) == 1


def mock_client(handler, monkeypatch) -> tuple[StressKitClient, list[float]]:
    sleeps: list[float] = []
    monkeypatch.setattr("stresskit_sdk.client.time.sleep", sleeps.append)

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(route), base_url="http://mock")
    return StressKitClient("http://mock", "id", "secret", http=http), sleeps


def test_retry_after_is_respected(monkeypatch):
    answers = [httpx.Response(429, headers={"Retry-After": "2"}, json={"title": "Slow down"})]

    def handler(request):
        return answers.pop() if answers else httpx.Response(200, json={"device_id": "w"})

    client, sleeps = mock_client(handler, monkeypatch)
    assert client.get_device("w") == {"device_id": "w"}
    assert sleeps == [2]


def test_client_errors_are_not_retried(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(404, json={"title": "Not Found", "status": 404})

    client, sleeps = mock_client(handler, monkeypatch)
    with pytest.raises(StressKitError):
        client.get_device("w")
    assert len(attempts) == 1 and sleeps == []


def expired_token() -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "demo-clinic-a",
              "tenant_id": "tenant-clinic-a", "iat": now - 7200, "exp": now - 3600}  # fmt: skip
    return jwt.encode(claims, DEMO_JWT_SECRET, algorithm="HS256")


def test_401_on_a_cached_token_gets_one_fresh_token(net):
    sdk = client_on(net)
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    # The SDK thinks its token is good for an hour (say the phone's clock was wrong).
    sdk._token, sdk._token_expires_at = expired_token(), time.time() + 3600
    assert sdk.get_device("watch-001")["device_id"] == "watch-001"


# --- SK-17: offline queue ------------------------------------------------------------------


def test_offline_upload_is_queued_and_sent_when_back_online(app, net, tmp_path):
    sdk = client_on(net, OfflineQueue(tmp_path / "q"))
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")

    net.offline = True
    pending = sdk.upload_recording("watch-001", recording(), STARTED_AT)
    assert pending["status"] == "queued"
    assert len(sdk.offline_queue) == 1 and uploads_in(app) == []

    net.offline = False
    out = sdk.drain_queue()
    assert out["remaining"] == 0 and out["failed"] == []
    assert sdk.wait_until_processed(out["sent"][0]["upload_id"])["status"] == "processed"


def test_queue_drains_oldest_first(app, net, tmp_path):
    sdk = client_on(net, OfflineQueue(tmp_path / "q"))
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.offline = True
    starts = [STARTED_AT + timedelta(hours=h) for h in range(3)]
    for start in starts:
        sdk.upload_recording("watch-001", recording(), start)
    net.offline = False
    sent = sdk.drain_queue()["sent"]
    started = [
        app.state.store.get_upload("tenant-clinic-a", s["upload_id"]).started_at for s in sent
    ]
    assert started == starts


def test_queue_survives_an_app_restart(net, tmp_path):
    first = client_on(net, OfflineQueue(tmp_path / "q"))
    first.register_device("watch-001", model="S1", firmware_version="1.0")
    net.offline = True
    first.upload_recording("watch-001", recording(), STARTED_AT)

    net.offline = False
    restarted = client_on(net, OfflineQueue(tmp_path / "q"))
    assert len(restarted.offline_queue) == 1
    assert len(restarted.drain_queue()["sent"]) == 1


def test_full_queue_raises_and_keeps_what_it_has(net, tmp_path):
    queue = OfflineQueue(tmp_path / "q", max_bytes=80_000)  # fits one 53 KB recording
    sdk = client_on(net, queue)
    net.offline = True
    sdk.upload_recording("watch-001", recording(), STARTED_AT)
    with pytest.raises(OfflineQueueFull):
        sdk.upload_recording("watch-001", recording(), STARTED_AT + timedelta(hours=1))
    assert len(queue) == 1


def test_token_expired_while_offline_does_not_fail_the_drain(net, tmp_path):
    sdk = client_on(net, OfflineQueue(tmp_path / "q"))
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.offline = True
    sdk.upload_recording("watch-001", recording(), STARTED_AT)
    net.offline = False
    sdk._token, sdk._token_expires_at = expired_token(), time.time() + 3600
    out = sdk.drain_queue()
    assert out["remaining"] == 0 and len(out["sent"]) == 1


def test_expired_upload_link_is_renewed_with_the_same_key(app, net, tmp_path, monkeypatch):
    sdk = client_on(net, OfflineQueue(tmp_path / "q"))
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    # The upload is created, then the network drops before the file is sent. By the time
    # the queue drains, the first link has long expired.
    real_time = time.time
    monkeypatch.setattr("stresskit_api.blobstore.time.time", lambda: real_time() - 3600)
    net.offline_methods = {"PUT"}
    assert sdk.upload_recording("watch-001", recording(), STARTED_AT)["status"] == "queued"
    assert len(uploads_in(app)) == 1

    monkeypatch.setattr("stresskit_api.blobstore.time.time", real_time)
    net.offline_methods = set()
    out = sdk.drain_queue()
    assert out["remaining"] == 0
    assert [u.upload_id for u in uploads_in(app)] == [out["sent"][0]["upload_id"]]


def test_refused_recording_is_set_aside_and_the_rest_continue(net, tmp_path):
    queue = OfflineQueue(tmp_path / "q")
    sdk = client_on(net, queue)
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.offline = True
    sdk.upload_recording("watch-404", recording(), STARTED_AT)  # never registered
    sdk.upload_recording("watch-001", recording(), STARTED_AT)
    net.offline = False
    out = sdk.drain_queue()
    assert len(out["sent"]) == 1 and len(out["failed"]) == 1
    assert "404" in out["failed"][0]["error"]
    assert len(queue) == 0 and len(list(queue.failed_dir.iterdir())) == 1


def test_bad_secret_keeps_the_whole_queue(net, tmp_path):
    queue = OfflineQueue(tmp_path / "q")
    sdk = client_on(net, queue)
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    net.offline = True
    for h in range(2):
        sdk.upload_recording("watch-001", recording(), STARTED_AT + timedelta(hours=h))
    net.offline = False

    # The customer rotated their secret while the phone was offline.
    sdk._client_secret, sdk._token = "rotated-away", None
    out = sdk.drain_queue()
    assert out["sent"] == [] and out["failed"] == [] and out["remaining"] == 2
    assert "401" in out["stopped"] and not queue.failed_dir.exists()

    sdk._client_secret = "demo-secret-a"  # fixed: everything still goes up
    assert len(sdk.drain_queue()["sent"]) == 2


def test_replay_after_the_file_arrived_has_no_link(sdk, http, auth_a):
    sdk.register_device("watch-001", model="S1", firmware_version="1.0")
    item_key = "same-key"
    ticket = sdk.create_upload(
        "watch-001", started_at=STARTED_AT, sample_rate_hz=25, duration_s=60,
        idempotency_key=item_key,
    )  # fmt: skip
    sdk.put_file(ticket["upload_url"], recording().to_json())
    sdk.complete_upload(ticket["upload_id"])
    replay = sdk.create_upload(
        "watch-001", started_at=STARTED_AT, sample_rate_hz=25, duration_s=60,
        idempotency_key=item_key,
    )  # fmt: skip
    assert replay["upload_id"] == ticket["upload_id"]
    assert replay["status"] != "pending_upload" and replay["upload_url"] is None
