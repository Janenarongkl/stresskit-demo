"""Request and response schemas. These are the API contract (see docs/openapi.json)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Seconds until the token expires.")
    scope: str


class DeviceCreate(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN, examples=["watch-001"])
    model: str = Field(max_length=64, examples=["StressBand S1"])
    firmware_version: str = Field(max_length=32, examples=["1.4.2"])


class Device(DeviceCreate):
    created_at: datetime


class UploadCreate(BaseModel):
    device_id: str = Field(pattern=ID_PATTERN)
    started_at: datetime = Field(description="Wall-clock time of the first sample (UTC).")
    sample_rate_hz: int = Field(ge=1, le=512, examples=[25])
    duration_s: int = Field(ge=60, le=24 * 3600, description="At least one 60 s window.")
    content_type: str = Field(default="application/json", pattern=r"^application/json$")


class UploadStatus(StrEnum):
    pending_upload = "pending_upload"
    processing = "processing"
    processed = "processed"
    failed = "failed"


class Upload(BaseModel):
    upload_id: str
    device_id: str
    status: UploadStatus
    started_at: datetime
    sample_rate_hz: int
    duration_s: int
    created_at: datetime
    window_count: int | None = None
    error: str | None = None


class UploadTicket(Upload):
    upload_url: str = Field(description="Pre-signed PUT URL. No Authorization header needed.")
    upload_url_expires_at: datetime


class StressLabel(StrEnum):
    stressed = "stressed"
    not_stressed = "not_stressed"
    na = "na"


class WindowResult(BaseModel):
    device_id: str
    upload_id: str
    window_start: datetime
    window_end: datetime
    label: StressLabel
    heart_rate_bpm: float | None
    signal_quality: str = Field(examples=["good", "motion", "poor_signal"])
    model_version: str


class ResultsPage(BaseModel):
    items: list[WindowResult]


class Problem(BaseModel):
    """RFC 9457 problem details, returned for every error as application/problem+json."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
