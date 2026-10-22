"""Metadata store: devices, uploads, results and idempotency records.

`InMemoryStore` is used locally and in tests. Milestone 4 adds a DynamoDB store with the
same methods. Every key starts with the tenant id, so one tenant can never read another
tenant's rows. In DynamoDB the tenant starts every partition key (layout in aws.py).
"""

from __future__ import annotations

import threading
from typing import Protocol

from .models import Device, Upload, WindowResult


class Store(Protocol):
    def put_device(self, tenant_id: str, device: Device) -> bool: ...
    def get_device(self, tenant_id: str, device_id: str) -> Device | None: ...
    def update_device(self, tenant_id: str, device: Device) -> None: ...
    def put_upload(self, tenant_id: str, upload: Upload) -> None: ...
    def get_upload(self, tenant_id: str, upload_id: str) -> Upload | None: ...
    def put_results(self, tenant_id: str, results: list[WindowResult]) -> None: ...
    def list_results(self, tenant_id: str, device_id: str, limit: int) -> list[WindowResult]: ...
    def get_idempotent(self, tenant_id: str, key: str) -> tuple[str, dict] | None: ...
    def put_idempotent(
        self, tenant_id: str, key: str, fingerprint: str, body: dict
    ) -> tuple[str, dict]:
        """Store the record unless one exists. Returns the record that is stored now."""
        ...


class InMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._devices: dict[tuple[str, str], Device] = {}
        self._uploads: dict[tuple[str, str], Upload] = {}
        self._results: dict[tuple[str, str], dict[str, WindowResult]] = {}
        self._idem: dict[tuple[str, str], tuple[str, dict]] = {}

    def put_device(self, tenant_id: str, device: Device) -> bool:
        """Insert if new. Returns False if the device already exists (no overwrite)."""
        with self._lock:
            key = (tenant_id, device.device_id)
            if key in self._devices:
                return False
            self._devices[key] = device
            return True

    def get_device(self, tenant_id: str, device_id: str) -> Device | None:
        return self._devices.get((tenant_id, device_id))

    def update_device(self, tenant_id: str, device: Device) -> None:
        with self._lock:
            self._devices[(tenant_id, device.device_id)] = device

    def put_upload(self, tenant_id: str, upload: Upload) -> None:
        with self._lock:
            self._uploads[(tenant_id, upload.upload_id)] = upload

    def get_upload(self, tenant_id: str, upload_id: str) -> Upload | None:
        return self._uploads.get((tenant_id, upload_id))

    def put_results(self, tenant_id: str, results: list[WindowResult]) -> None:
        with self._lock:
            for r in results:
                # Keyed by window start, so reprocessing an upload overwrites, never duplicates.
                bucket = self._results.setdefault((tenant_id, r.device_id), {})
                bucket[r.window_start.isoformat()] = r

    def list_results(self, tenant_id: str, device_id: str, limit: int) -> list[WindowResult]:
        bucket = self._results.get((tenant_id, device_id), {})
        return [bucket[k] for k in sorted(bucket)][-limit:]

    def get_idempotent(self, tenant_id: str, key: str) -> tuple[str, dict] | None:
        return self._idem.get((tenant_id, key))

    def put_idempotent(
        self, tenant_id: str, key: str, fingerprint: str, body: dict
    ) -> tuple[str, dict]:
        with self._lock:
            return self._idem.setdefault((tenant_id, key), (fingerprint, body))
