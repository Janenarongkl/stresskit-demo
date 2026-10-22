"""The worker: turns an uploaded recording into per-window results.

Locally this runs as a FastAPI background task right after `/complete` returns 202.
In AWS (milestone 5) the same function runs in a worker Lambda fed by an SQS queue, with a
dead-letter queue for uploads that keep failing.
"""

from __future__ import annotations

import json
from datetime import timedelta

from . import mock_model
from .blobstore import BlobStore
from .models import UploadStatus, WindowResult
from .store import Store


def blob_key(tenant_id: str, device_id: str, upload_id: str) -> str:
    return f"{tenant_id}/{device_id}/{upload_id}.json"


DEFAULT_MAX_BYTES = 10 * 1024 * 1024


def process_upload(
    store: Store,
    blobs: BlobStore,
    tenant_id: str,
    upload_id: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    upload = store.get_upload(tenant_id, upload_id)
    if upload is None or upload.status != UploadStatus.processing:
        return
    key = blob_key(tenant_id, upload.device_id, upload_id)
    try:
        # An S3 pre-signed PUT cannot cap the file size, so the worker checks before reading.
        if blobs.size(key) > max_bytes:
            raise ValueError(f"recording is larger than the {max_bytes} byte limit")
        raw = json.loads(blobs.read(key))
        ppg, acc = raw["ppg"], raw["acc"]
        if not isinstance(ppg, list) or not isinstance(acc, list) or len(ppg) != len(acc):
            raise ValueError("ppg and acc must be lists of the same length")
        windows = mock_model.analyse(ppg, acc, upload.sample_rate_hz)
        if not windows:
            raise ValueError("recording is shorter than one 60 s window")
    except (ValueError, KeyError, TypeError) as exc:
        store.put_upload(
            tenant_id, upload.model_copy(update={"status": UploadStatus.failed, "error": str(exc)})
        )
        return

    window = timedelta(seconds=mock_model.WINDOW_S)
    results = [
        WindowResult(
            device_id=upload.device_id,
            upload_id=upload_id,
            window_start=upload.started_at + w.index * window,
            window_end=upload.started_at + (w.index + 1) * window,
            label=w.label,
            heart_rate_bpm=w.heart_rate_bpm,
            signal_quality=w.signal_quality,
            model_version=mock_model.MODEL_VERSION,
        )
        for w in windows
    ]
    store.put_results(tenant_id, results)
    store.put_upload(
        tenant_id,
        upload.model_copy(update={"status": UploadStatus.processed, "window_count": len(results)}),
    )
