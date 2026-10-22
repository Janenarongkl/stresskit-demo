"""The worker: turns an uploaded recording into per-window results.

Locally this runs as a FastAPI background task right after `/complete` returns 202.
In AWS (milestone 5) the same function runs in a worker Lambda fed by an SQS queue, with a
dead-letter queue for uploads that keep failing.
"""

from __future__ import annotations

import json
from datetime import timedelta

from . import mock_model
from .blobstore import LocalBlobStore
from .models import UploadStatus, WindowResult
from .store import Store


def blob_key(tenant_id: str, device_id: str, upload_id: str) -> str:
    return f"{tenant_id}/{device_id}/{upload_id}.json"


def process_upload(store: Store, blobs: LocalBlobStore, tenant_id: str, upload_id: str) -> None:
    upload = store.get_upload(tenant_id, upload_id)
    if upload is None or upload.status != UploadStatus.processing:
        return
    try:
        raw = json.loads(blobs.read(blob_key(tenant_id, upload.device_id, upload_id)))
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
