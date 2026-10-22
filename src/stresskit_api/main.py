"""The HTTPS API. Run locally with:  uvicorn stresskit_api.main:app --reload

Endpoints (all under /v1, all need a bearer token except /oauth/token and the signed blob URL):

    POST /v1/oauth/token                 client credentials -> JWT
    POST /v1/devices                     register a wearable
    GET  /v1/devices/{device_id}
    PATCH /v1/devices/{device_id}         record a firmware upgrade
    POST /v1/uploads                     ask for a pre-signed upload URL (Idempotency-Key)
    PUT  /v1/blobs/{key}?signature=...   upload the raw file (stands in for S3)
    POST /v1/uploads/{upload_id}/complete   "file is there, please process" -> 202
    GET  /v1/uploads/{upload_id}         status: pending_upload | processing | processed | failed
    GET  /v1/results?device_id=...       one stress label per 60 s window
"""

# No "from __future__ import annotations" here: FastAPI must resolve the Annotated aliases
# defined inside create_app() at runtime.
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import Principal, get_settings, issue_token, require_principal
from .blobstore import BlobStore, LocalBlobStore
from .models import (
    ID_PATTERN,
    Device,
    DeviceCreate,
    DeviceUpdate,
    Problem,
    ResultsPage,
    TokenResponse,
    Upload,
    UploadCreate,
    UploadStatus,
    UploadTicket,
)
from .processing import blob_key, process_upload
from .settings import Settings
from .store import InMemoryStore, Store

PROBLEM_JSON = "application/problem+json"
ERRORS = {
    401: {"model": Problem, "description": "Missing, invalid or expired token."},
    404: {"model": Problem, "description": "Not found for this tenant."},
    422: {"model": Problem, "description": "Request body or query is invalid."},
}

DESCRIPTION = """
Demo backend for a wearable stress-detection product. A device (or the customer's app)
uses the Python SDK to get a token, register the device, upload a PPG + accelerometer
recording through a pre-signed URL, and read back one stress label per 60-second window.

All errors use [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details.
**Demo credentials** (public, demo only): `demo-clinic-a` / `demo-secret-a`.
"""


def _problem(status: int, detail: str | None, headers: dict | None = None, **extra) -> JSONResponse:
    title = {
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        409: "Conflict",
        413: "Payload Too Large",
        422: "Unprocessable Content",
    }.get(status, "Error")
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail, **extra}
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="StressKit API", version="0.4.0", description=DESCRIPTION)
    app.state.settings = settings
    if settings.backend == "aws":
        from .aws import DynamoStore, S3BlobStore

        if not (settings.bucket and settings.table):
            raise RuntimeError("STRESSKIT_BACKEND=aws needs STRESSKIT_BUCKET and STRESSKIT_TABLE.")
        app.state.store = store or DynamoStore(settings.table, settings.aws_region)
        app.state.blobs = S3BlobStore(settings.bucket, settings.aws_region)
    else:
        app.state.store = store or InMemoryStore()
        app.state.blobs = LocalBlobStore(settings.data_dir / "blobs", settings.blob_signing_key)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, str(exc.detail), getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _problem(422, "Request validation failed.", errors=errors)

    def get_store(request: Request) -> Store:
        return request.app.state.store

    def get_blobs(request: Request) -> BlobStore:
        return request.app.state.blobs

    AuthDep = Annotated[Principal, Depends(require_principal)]
    StoreDep = Annotated[Store, Depends(get_store)]
    BlobsDep = Annotated[BlobStore, Depends(get_blobs)]

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post(
        "/v1/oauth/token", response_model=TokenResponse, tags=["auth"], responses={401: ERRORS[401]}
    )
    def token(
        grant_type: Annotated[str, Form(pattern="^client_credentials$")],
        client_id: Annotated[str, Form()],
        client_secret: Annotated[str, Form()],
        s: Settings = Depends(get_settings),
    ) -> dict:
        """OAuth 2.0 client-credentials grant (form-encoded, per RFC 6749 section 4.4)."""
        return issue_token(s, client_id, client_secret)

    @app.post(
        "/v1/devices",
        status_code=201,
        response_model=Device,
        tags=["devices"],
        responses={**ERRORS, 409: {"model": Problem}},
    )
    def create_device(body: DeviceCreate, who: AuthDep, store: StoreDep) -> Device:
        device = Device(**body.model_dump(), created_at=datetime.now(UTC))
        if not store.put_device(who.tenant_id, device):
            raise HTTPException(409, f"Device {body.device_id} is already registered.")
        return device

    @app.get("/v1/devices/{device_id}", response_model=Device, tags=["devices"], responses=ERRORS)
    def get_device(device_id: str, who: AuthDep, store: StoreDep) -> Device:
        device = store.get_device(who.tenant_id, device_id)
        if device is None:
            raise HTTPException(404, f"Device {device_id} not found.")
        return device

    @app.patch("/v1/devices/{device_id}", response_model=Device, tags=["devices"], responses=ERRORS)
    def update_device(device_id: str, body: DeviceUpdate, who: AuthDep, store: StoreDep) -> Device:
        """Record a firmware upgrade. Uploads created earlier keep the version they recorded."""
        device = store.get_device(who.tenant_id, device_id)
        if device is None:
            raise HTTPException(404, f"Device {device_id} not found.")
        device = device.model_copy(
            update={"firmware_version": body.firmware_version, "updated_at": datetime.now(UTC)}
        )
        store.update_device(who.tenant_id, device)
        return device

    def ticket_for(upload: Upload, tenant_id: str, request: Request, blobs: BlobStore) -> dict:
        """The upload plus a pre-signed link, which is only useful while no file has arrived."""
        if upload.status != UploadStatus.pending_upload:
            return upload.model_dump(mode="json") | {
                "upload_url": None,
                "upload_url_expires_at": None,
            }
        base_url = settings.public_base_url or str(request.base_url)
        url, expires = blobs.presign_put(
            blob_key(tenant_id, upload.device_id, upload.upload_id),
            base_url,
            settings.upload_url_ttl_s,
        )
        return UploadTicket(
            **upload.model_dump(),
            upload_url=url,
            upload_url_expires_at=datetime.fromtimestamp(expires, UTC),
        ).model_dump(mode="json")

    @app.post(
        "/v1/uploads",
        status_code=201,
        response_model=UploadTicket,
        tags=["uploads"],
        responses={
            **ERRORS,
            409: {
                "model": Problem,
                "description": "Idempotency-Key reused with a different request body.",
            },
        },
    )
    def create_upload(
        body: UploadCreate,
        request: Request,
        who: AuthDep,
        store: StoreDep,
        blobs: BlobsDep,
        idempotency_key: Annotated[
            str | None,
            Header(
                max_length=128,
                description="Retry-safe key; same key returns the "
                "same upload instead of creating a second one.",
            ),
        ] = None,
    ) -> JSONResponse | dict:
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        if idempotency_key:
            seen = store.get_idempotent(who.tenant_id, idempotency_key)
            if seen is not None:
                if seen[0] != fingerprint:
                    raise HTTPException(409, "Idempotency-Key was used with a different body.")
                # Same upload as the first time. If the file was never sent, issue a fresh link:
                # a retry from an offline queue may come long after the first link expired.
                upload = store.get_upload(who.tenant_id, seen[1]["upload_id"])
                replay = ticket_for(upload, who.tenant_id, request, blobs) if upload else seen[1]
                return JSONResponse(
                    replay, status_code=201, headers={"Idempotent-Replayed": "true"}
                )

        device = store.get_device(who.tenant_id, body.device_id)
        if device is None:
            raise HTTPException(404, f"Device {body.device_id} not found.")

        upload_id = "upl_" + uuid.uuid4().hex[:20]
        upload = Upload(
            upload_id=upload_id,
            device_id=body.device_id,
            status=UploadStatus.pending_upload,
            started_at=body.started_at,
            sample_rate_hz=body.sample_rate_hz,
            duration_s=body.duration_s,
            created_at=datetime.now(UTC),
            firmware_version=device.firmware_version,
        )
        store.put_upload(who.tenant_id, upload)
        result = ticket_for(upload, who.tenant_id, request, blobs)
        if idempotency_key:
            store.put_idempotent(who.tenant_id, idempotency_key, fingerprint, result)
        return result

    @app.put(
        "/v1/blobs/{key:path}",
        tags=["uploads"],
        responses={403: {"model": Problem}, 413: {"model": Problem}},
    )
    async def put_blob(
        key: str,
        request: Request,
        blobs: BlobsDep,
        expires: Annotated[int, Query()],
        signature: Annotated[str, Query()],
    ) -> dict:
        """Local stand-in for an S3 pre-signed PUT. Authorised by the signature, not a token."""
        if not isinstance(blobs, LocalBlobStore):
            raise HTTPException(404, "Uploads go straight to S3 on this deployment.")
        reason = blobs.verify("PUT", key, expires, signature)
        if reason:
            raise HTTPException(403, reason)
        if int(request.headers.get("content-length") or 0) > settings.max_upload_bytes:
            raise HTTPException(413, "Recording is larger than the upload limit.")
        data = await request.body()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "Recording is larger than the upload limit.")
        blobs.write(key, data)
        return {"key": key, "bytes": len(data)}

    def _get_upload(store: Store, tenant_id: str, upload_id: str) -> Upload:
        upload = store.get_upload(tenant_id, upload_id)
        if upload is None:
            raise HTTPException(404, f"Upload {upload_id} not found.")
        return upload

    @app.post(
        "/v1/uploads/{upload_id}/complete",
        status_code=202,
        response_model=Upload,
        tags=["uploads"],
        responses={**ERRORS, 409: {"model": Problem}},
    )
    def complete_upload(
        upload_id: str,
        who: AuthDep,
        store: StoreDep,
        blobs: BlobsDep,
        background: BackgroundTasks,
    ) -> Upload:
        """Starts processing and returns 202 Accepted at once. Poll GET /v1/uploads/{id}.

        Calling it again is safe: it returns the current state and does not re-queue.
        """
        upload = _get_upload(store, who.tenant_id, upload_id)
        if upload.status != UploadStatus.pending_upload:
            return upload
        if not blobs.exists(blob_key(who.tenant_id, upload.device_id, upload_id)):
            raise HTTPException(409, "No file was uploaded to the upload URL yet.")
        upload = upload.model_copy(update={"status": UploadStatus.processing})
        store.put_upload(who.tenant_id, upload)
        background.add_task(
            process_upload, store, blobs, who.tenant_id, upload_id, settings.max_upload_bytes
        )
        return upload

    @app.get("/v1/uploads/{upload_id}", response_model=Upload, tags=["uploads"], responses=ERRORS)
    def get_upload(upload_id: str, who: AuthDep, store: StoreDep) -> Upload:
        return _get_upload(store, who.tenant_id, upload_id)

    @app.get("/v1/results", response_model=ResultsPage, tags=["results"], responses=ERRORS)
    def list_results(
        who: AuthDep,
        store: StoreDep,
        device_id: Annotated[str, Query(pattern=ID_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=1440)] = 100,
    ) -> ResultsPage:
        """Latest windows for a device, oldest first."""
        if store.get_device(who.tenant_id, device_id) is None:
            raise HTTPException(404, f"Device {device_id} not found.")
        return ResultsPage(items=store.list_results(who.tenant_id, device_id, limit))

    return app


app = create_app()
