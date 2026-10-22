# stresskit-sdk

The Python client for the [StressKit demo](https://github.com/Janenarongkl/stresskit-demo) API.

```bash
pip install stresskit_sdk-0.4.0-py3-none-any.whl   # from the GitHub release
```

```python
from stresskit_sdk import OfflineQueue, StressKitClient

client = StressKitClient(
    "https://api.example",
    "demo-clinic-a",
    "demo-secret-a",
    offline_queue=OfflineQueue("~/.stresskit/queue"),
)
client.register_device("watch-001", model="StressBand S1", firmware_version="1.4.2")
result = client.upload_recording("watch-001", recording, started_at)  # queued if offline
client.drain_queue()  # when back online
```

It only depends on `httpx`. Versions follow semantic versioning; see `CHANGELOG.md` in the repository.
