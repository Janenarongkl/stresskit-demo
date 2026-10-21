import time

import jwt

from stresskit_api.auth import AUDIENCE, ISSUER
from stresskit_api.settings import DEMO_JWT_SECRET


def test_token_has_tenant_claim(http):
    resp = http.post(
        "/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "demo-clinic-a",
            "client_secret": "demo-secret-a",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "Bearer"
    claims = jwt.decode(
        body["access_token"], DEMO_JWT_SECRET, algorithms=["HS256"], audience=AUDIENCE
    )
    assert claims["tenant_id"] == "tenant-clinic-a"


def test_wrong_secret_is_401_problem_json(http):
    resp = http.post(
        "/v1/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "demo-clinic-a",
            "client_secret": "x",
        },
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"] == "application/problem+json"
    assert resp.json()["title"] == "Unauthorized"


def test_unsupported_grant_type_is_422(http):
    resp = http.post(
        "/v1/oauth/token",
        data={
            "grant_type": "password",
            "client_id": "demo-clinic-a",
            "client_secret": "demo-secret-a",
        },
    )
    assert resp.status_code == 422


def test_missing_token_is_401(http):
    resp = http.get("/v1/devices/watch-001")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_401(http):
    now = int(time.time())
    expired = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "demo-clinic-a",
            "tenant_id": "tenant-clinic-a",
            "iat": now - 7200,
            "exp": now - 3600,
        },
        DEMO_JWT_SECRET,
        algorithm="HS256",
    )
    resp = http.get("/v1/devices/watch-001", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Token expired."


def test_token_signed_with_other_key_is_401(http):
    forged = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "x",
            "tenant_id": "tenant-clinic-a",
            "exp": int(time.time()) + 60,
        },
        "attacker-key-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )
    resp = http.get("/v1/devices/watch-001", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
