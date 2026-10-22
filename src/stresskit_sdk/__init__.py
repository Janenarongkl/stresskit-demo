"""StressKit Python SDK: what a customer installs to talk to the API.

    from stresskit_sdk import StressKitClient
    client = StressKitClient("http://127.0.0.1:8000", "demo-clinic-a", "demo-secret-a")
    client.register_device("watch-001", model="StressBand S1", firmware_version="1.4.2")
    upload = client.upload_recording("watch-001", recording, started_at)
    client.wait_until_processed(upload["upload_id"])
    windows = client.get_results("watch-001")

The SDK hides the protocol: token caching and refresh, the three-step upload, retries with
the same Idempotency-Key, and turning error responses into exceptions.
"""

from .client import StressKitClient, StressKitError

__all__ = ["StressKitClient", "StressKitError"]
