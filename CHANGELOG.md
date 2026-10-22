# Changelog

Versions of the SDK (`stresskit-sdk`) and the API contract. The SDK follows [semantic versioning](https://semver.org/): a breaking change bumps the major version.

## SDK 0.4.0 and API 0.4.0 (milestone 4)

### Added
- The API can run on AWS storage: `STRESSKIT_BACKEND=aws` keeps devices, uploads, results and idempotency keys in DynamoDB and raw recordings in S3. Phones upload straight to S3 with a pre-signed URL. The API contract does not change.
- Secrets can come from SSM Parameter Store (`STRESSKIT_SSM_PREFIX`).
- `infra/template.yaml`: the S3 bucket, DynamoDB table and least-privilege IAM roles, deployed with `sam deploy` (see `docs/aws/deploy-m4.md`).
- SDK: `upload_http` lets the file upload use its own HTTP client (the upload URL points at S3, not the API). A successful upload with an empty response body is handled.

### Changed
- The worker marks an upload `failed` when its file is over the size limit. An S3 pre-signed URL cannot cap the size the way the local upload route does.

## SDK 0.3.0 and API (milestone 3)

### Added
- Offline queue (`OfflineQueue`): recordings made without a network are kept on disk and sent oldest first by `drain_queue()`, each with the Idempotency-Key it was given when queued.
- `update_device()` to record a firmware upgrade (`PATCH /v1/devices/{id}`).
- Uploads now record the device's `firmware_version` at creation.
- The SDK respects `Retry-After` on `429`, and gets one fresh token when the server answers `401` to a cached one.
- The SDK is built as its own wheel with only `httpx` as a dependency, and tags `sdk-v*` publish it as a GitHub release.

### Changed
- An `Idempotency-Key` replay for an upload whose file has not arrived returns a fresh `upload_url`, so a recording queued for longer than 15 minutes can still be sent.
- `drain_queue()` stops and keeps recordings queued on `401` or `403` (for example, a rotated secret), and its result says why in `stopped`. Only permanent refusals go to `failed/`.

### Contract
- `upload_url` and `upload_url_expires_at` in `POST /v1/uploads` responses can now be `null`: an `Idempotency-Key` replay after the file has arrived returns no link. Clients that assumed a string must handle `null` (decision D14).

## 0.2.0 (milestones 1 and 2)

- First version of the v1 API, the SDK, the simulator and the mock model.
