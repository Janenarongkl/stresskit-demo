"""Configuration, read from environment variables.

The defaults below are DEMO VALUES ONLY. They are public (this repo is public) and exist
so the demo runs with zero setup. Anything real must come from the environment, and in AWS
from SSM Parameter Store or Secrets Manager.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEMO_JWT_SECRET = "demo-only-jwt-signing-key-not-a-real-secret"
DEMO_BLOB_SIGNING_KEY = "demo-only-blob-signing-key-not-a-real-secret"

# client_id -> (client_secret, tenant_id). Two tenants so tenant isolation can be shown.
DEMO_CLIENTS = {
    "demo-clinic-a": {"secret": "demo-secret-a", "tenant_id": "tenant-clinic-a"},
    "demo-clinic-b": {"secret": "demo-secret-b", "tenant_id": "tenant-clinic-b"},
}


@dataclass(frozen=True)
class ApiClient:
    client_id: str
    client_secret: str
    tenant_id: str


@dataclass(frozen=True)
class Settings:
    jwt_secret: str = DEMO_JWT_SECRET
    blob_signing_key: str = DEMO_BLOB_SIGNING_KEY
    token_ttl_s: int = 3600
    upload_url_ttl_s: int = 900
    max_upload_bytes: int = 10 * 1024 * 1024
    data_dir: Path = Path(".data")
    # Set when the API sits behind a proxy or API Gateway, so upload URLs use the public host.
    public_base_url: str | None = None
    clients: dict[str, ApiClient] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        raw_clients = os.environ.get("STRESSKIT_CLIENTS")
        client_map = json.loads(raw_clients) if raw_clients else DEMO_CLIENTS
        clients = {
            cid: ApiClient(cid, c["secret"], c["tenant_id"]) for cid, c in client_map.items()
        }
        return cls(
            jwt_secret=os.environ.get("STRESSKIT_JWT_SECRET", DEMO_JWT_SECRET),
            blob_signing_key=os.environ.get("STRESSKIT_BLOB_SIGNING_KEY", DEMO_BLOB_SIGNING_KEY),
            token_ttl_s=int(os.environ.get("STRESSKIT_TOKEN_TTL_S", "3600")),
            upload_url_ttl_s=int(os.environ.get("STRESSKIT_UPLOAD_URL_TTL_S", "900")),
            data_dir=Path(os.environ.get("STRESSKIT_DATA_DIR", ".data")),
            public_base_url=os.environ.get("STRESSKIT_PUBLIC_BASE_URL") or None,
            clients=clients,
        )
