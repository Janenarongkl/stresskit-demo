import dataclasses
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from stresskit_api import create_app
from stresskit_api.settings import Settings
from stresskit_sdk import StressKitClient

STARTED_AT = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


@pytest.fixture
def app(tmp_path):
    return create_app(dataclasses.replace(Settings.from_env(), data_dir=tmp_path))


@pytest.fixture
def http(app):
    with TestClient(app) as client:
        yield client


def token_for(http, client_id="demo-clinic-a", secret="demo-secret-a") -> str:
    resp = http.post(
        "/v1/oauth/token",
        data={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
def auth_a(http):
    return {"Authorization": f"Bearer {token_for(http)}"}


@pytest.fixture
def auth_b(http):
    return {"Authorization": f"Bearer {token_for(http, 'demo-clinic-b', 'demo-secret-b')}"}


@pytest.fixture
def sdk(http):
    return StressKitClient("http://testserver", "demo-clinic-a", "demo-secret-a", http=http)
