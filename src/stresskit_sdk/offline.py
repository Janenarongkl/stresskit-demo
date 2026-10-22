"""A small on-disk queue for recordings made while the phone has no network.

Each recording is one JSON file, named so that sorting the names gives the oldest first. A
file is written to a temporary name and then renamed, so a crash never leaves half a file in
the queue. The Idempotency-Key is chosen when the recording is queued and kept with it: if the
first attempt reached the server before the network dropped, the retry finds the same upload.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_MAX_BYTES = 50 * 1024 * 1024


class OfflineQueueFull(Exception):
    """The queue has reached its size limit. Nothing already queued was dropped."""


class OfflineQueue:
    def __init__(self, directory: str | Path, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.directory = Path(directory)
        self.failed_dir = self.directory / "failed"
        self.max_bytes = max_bytes
        self.directory.mkdir(parents=True, exist_ok=True)

    def _files(self) -> list[Path]:
        return sorted(self.directory.glob("*.json"))

    def __len__(self) -> int:
        return len(self._files())

    def size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._files())

    def add(self, item: dict[str, Any]) -> str:
        """Store one recording. Returns its queue id. Raises OfflineQueueFull if it won't fit."""
        data = json.dumps(item).encode()
        if self.size_bytes() + len(data) > self.max_bytes:
            raise OfflineQueueFull(
                f"Offline queue is full ({self.max_bytes} bytes); recording was not queued."
            )
        queue_id = f"{time.time_ns():020d}-{item['idempotency_key'][:8]}"
        tmp = self.directory / f".{queue_id}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, self.directory / f"{queue_id}.json")
        return queue_id

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        """Queued recordings, oldest first."""
        return [(p.stem, json.loads(p.read_bytes())) for p in self._files()]

    def remove(self, queue_id: str) -> None:
        (self.directory / f"{queue_id}.json").unlink(missing_ok=True)

    def set_aside(self, queue_id: str, reason: str) -> None:
        """Move a recording the server refused (for example, an unknown device) out of the way."""
        self.failed_dir.mkdir(exist_ok=True)
        src = self.directory / f"{queue_id}.json"
        item = json.loads(src.read_bytes())
        (self.failed_dir / f"{queue_id}.json").write_text(json.dumps({**item, "error": reason}))
        src.unlink()
