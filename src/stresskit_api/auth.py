"""OAuth2 client-credentials tokens (JWT) and the dependency that checks them.

Flow: a customer's backend or the SDK sends client_id + client_secret once to
POST /v1/oauth/token and gets a short-lived JWT. Every other call sends
`Authorization: Bearer <jwt>`. The JWT carries the tenant, so the API never trusts a
tenant id sent in the request body.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .settings import Settings

ISSUER = "stresskit-demo"
AUDIENCE = "stresskit-api"
SCOPE = "devices:write uploads:write results:read"

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    client_id: str
    tenant_id: str


def issue_token(settings: Settings, client_id: str, client_secret: str) -> dict:
    client = settings.clients.get(client_id)
    # compare_digest takes the same time whether the secret is close or not.
    if client is None or not hmac.compare_digest(client.client_secret, client_secret):
        raise HTTPException(status_code=401, detail="Invalid client credentials.")
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": client.client_id,
        "tenant_id": client.tenant_id,
        "scope": SCOPE,
        "iat": now,
        "exp": now + settings.token_ttl_s,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.token_ttl_s,
        "scope": SCOPE,
    }


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if creds is None:
        raise HTTPException(
            status_code=401,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = jwt.decode(
            creds.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    return Principal(client_id=claims["sub"], tenant_id=claims["tenant_id"])
