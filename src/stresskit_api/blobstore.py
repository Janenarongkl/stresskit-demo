"""Raw-data storage with pre-signed upload URLs.

Locally, files go to a folder and the URL is signed with HMAC-SHA256 over the method, key
and expiry, which is the same idea as an S3 pre-signed URL. Milestone 4 swaps this class for
S3 (`generate_presigned_url("put_object", ...)`) and the device uploads straight to S3.

Why pre-signed URLs: big sensor files skip the API (and Lambda's 6 MB payload limit), the
URL works for one object only, and it stops working after a few minutes.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_-]{1,64}\.json$")


class BlobStore(Protocol):
    """What the API and the worker need from raw-file storage (local folder or S3)."""

    def presign_put(self, key: str, base_url: str, ttl_s: int) -> tuple[str, int]: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int: ...
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes) -> None: ...


class LocalBlobStore:
    def __init__(self, root: Path, signing_key: str) -> None:
        self.root = root
        self._key = signing_key.encode()

    def _sign(self, method: str, key: str, expires: int) -> str:
        msg = f"{method}\n{key}\n{expires}".encode()
        return hmac.new(self._key, msg, hashlib.sha256).hexdigest()

    def presign_put(self, key: str, base_url: str, ttl_s: int) -> tuple[str, int]:
        expires = int(time.time()) + ttl_s
        query = urlencode({"expires": expires, "signature": self._sign("PUT", key, expires)})
        return f"{base_url.rstrip('/')}/v1/blobs/{key}?{query}", expires

    def verify(self, method: str, key: str, expires: int, signature: str) -> str | None:
        """Returns None if valid, otherwise the reason it is not."""
        if not KEY_PATTERN.match(key):
            return "Unknown object key."
        if not hmac.compare_digest(self._sign(method, key, expires), signature):
            return "Signature does not match."
        if time.time() > expires:
            return "Upload URL has expired."
        return None

    def _path(self, key: str) -> Path:
        if not KEY_PATTERN.match(key):
            raise ValueError("bad key")
        return self.root / key

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()
