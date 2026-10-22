# StressKit product backlog

Epics, user stories and acceptance criteria for the demo. Each story has an ID that the [traceability matrix](traceability.md) and commit messages can refer to.

- **Status:** Done (built and tested), Planned (milestone 3 to 6), Later (not scheduled).
- **Priority:** MoSCoW for the demo. Must = the demo is not credible without it.
- **Size:** story points, relative (1, 2, 3, 5, 8). Used to compare stories, not to promise dates.
- **Evidence:** the test that proves the acceptance criteria today. Stories without a test say how to check them by hand.

## Personas

| Persona | Who they are | What they care about |
|---|---|---|
| **Customer developer** | Builds the clinic's or wellness company's phone app. Integrates our SDK. | Clear contract, few surprises, errors they can act on, one-day integration |
| **Clinic reviewer** | A nurse, coach or HR wellness lead who looks at results in the customer's dashboard | One honest label per minute, knowing when data is unreliable |
| **Wearer** | The person wearing the watch | Privacy, battery, results that match how they felt |
| **Operations engineer** | Runs StressKit in the cloud | Failed uploads are visible, tenants stay apart, cost stays low |
| **Product owner** | Owns the roadmap and the model's place in it | Traceability from a result back to the data, model version and firmware |

## Epic map

| Epic | Goal | Milestone | Status |
|---|---|---|---|
| E1 Customer access | Each customer signs in as a machine and only ever acts as their own tenant | 2 | Done |
| E2 Device registry | Customers register watches so results can be traced to hardware and firmware | 2 | Done |
| E3 Upload recordings | Large recordings reach storage safely over unreliable phone networks | 2 | Done |
| E4 Processing and results | Each minute gets an honest label with quality and model version | 2 | Done |
| E5 Developer experience | A developer can integrate in a day from the SDK, docs and errors | 2, 3 | Partly done |
| E6 SDK robustness | Recordings survive offline periods and large sessions | 3 | Planned |
| E7 Run on AWS | Same contract, running serverless in ap-southeast-7 with a capped cost | 4, 5 | Planned |
| E8 Notify and operate | Customers hear when results are ready; we see failures before customers do | 6 | Planned |

---

## E1 Customer access

### SK-1 Get an access token
**As a** customer developer, **I want** to exchange my client ID and secret for a short-lived token, **so that** my app never sends the long-lived secret on every call.

Must · 3 points · Done

- **Given** a valid client ID and secret, **when** the app calls `POST /v1/oauth/token` with `grant_type=client_credentials`, **then** it gets `200` with a bearer token that expires in 3600 seconds.
- **Given** a token, **when** it is decoded, **then** it names the tenant (`tenant_id`) and an expiry, and is signed by StressKit.
- **Given** a wrong secret, **then** the answer is `401` as `application/problem+json`, and no token is issued.
- **Given** any grant type other than `client_credentials`, **then** the answer is `422`.

Evidence: `test_token_has_tenant_claim`, `test_wrong_secret_is_401_problem_json`, `test_unsupported_grant_type_is_422`

### SK-2 Reject calls without a valid token
**As an** operations engineer, **I want** every data call to require a valid, unexpired token, **so that** nobody reaches health data without signing in.

Must · 2 points · Done

- **Given** no `Authorization` header, **then** `401` with `WWW-Authenticate: Bearer`.
- **Given** an expired token, **then** `401`.
- **Given** a token signed with any other key, **then** `401`.

Evidence: `test_missing_token_is_401`, `test_expired_token_is_401`, `test_token_signed_with_other_key_is_401`

### SK-3 Keep tenants apart
**As a** clinic reviewer, **I want** another customer to be unable to see or even detect our devices, uploads and results, **so that** our patients' data stays private.

Must · 3 points · Done

- **Given** Clinic B's valid token, **when** it asks for Clinic A's device, upload or results by ID, **then** the answer is `404`, the same as for an ID that does not exist.
- **Given** both clinics register a device with the same ID, **then** each sees only its own.
- The tenant always comes from the token. No request field can choose the tenant.

Evidence: `test_tenant_isolation`

---

## E2 Device registry

### SK-4 Register a watch
**As a** customer developer, **I want** to register each watch with its model and firmware version, **so that** every result can be traced back to the hardware that produced it.

Must · 2 points · Done

- **Given** a new device ID (letters, digits, `-` and `_`, up to 64 characters), **when** the app calls `POST /v1/devices`, **then** `201` with the stored device and `created_at`.
- **Given** the same device ID again for the same tenant, **then** `409` and nothing changes.
- **Given** an invalid device ID, **then** `422` as problem+json.
- `GET /v1/devices/{device_id}` returns the device for its own tenant only.

Evidence: `test_duplicate_device_is_409`, `test_bad_device_id_is_422_problem`, `test_end_to_end_with_sdk`

### SK-5 Update firmware version
**As a** product owner, **I want** the firmware version on a device to be updated when the watch is upgraded, **so that** results recorded after the upgrade are traced to the right firmware.

Should · 2 points · Later

- **Given** a registered device, **when** the app sends `PATCH /v1/devices/{id}` with a new `firmware_version`, **then** `200` and later uploads record the new version.
- Each upload stores the firmware version that was current when it was created, so older results keep the old version.

---

## E3 Upload recordings

### SK-6 Upload a recording without passing it through the API
**As a** customer developer, **I want** to get a one-time upload link and send the file straight to storage, **so that** large recordings upload quickly and the API stays small and cheap.

Must · 5 points · Done

- **Given** a registered device, **when** the app calls `POST /v1/uploads` with `device_id`, `started_at`, `sample_rate_hz` and `duration_s`, **then** `201` with an `upload_id`, status `pending_upload` and an `upload_url`.
- The link allows writing exactly one file, in the tenant's own folder, and expires after 15 minutes.
- **When** the app `PUT`s the file to the link, **then** `200` with the stored size. No bearer token is needed for this call.
- **Given** a link whose path or expiry was changed, or that has expired, **then** `403`.

Evidence: `test_tampered_or_expired_upload_url_is_403`, `test_end_to_end_with_sdk`

### SK-7 Retry safely after a network drop
**As a** customer developer, **I want** to retry an upload request with the same `Idempotency-Key` and get the same upload back, **so that** a lost reply never creates duplicates.

Must · 3 points · Done

- **Given** a request that already succeeded, **when** the same key and the same body are sent again, **then** the same `upload_id` comes back with `Idempotent-Replayed: true`.
- **Given** the same key with a different body, **then** `409` and nothing new is created.

Evidence: `test_idempotency_key_replays_same_upload`, `test_idempotency_key_with_different_body_is_409`

### SK-8 Start processing only when the file is there
**As an** operations engineer, **I want** processing to start only after the file is in storage, **so that** the worker never runs on a missing file.

Must · 2 points · Done

- **Given** the file was uploaded, **when** the app calls `POST /v1/uploads/{id}/complete`, **then** `202` with status `processing`, within one second.
- **Given** no file was uploaded yet, **then** `409` and the upload stays `pending_upload`.
- **Given** `/complete` is called again, **then** it returns the current state and does not queue the work twice.

Evidence: `test_complete_before_file_is_409`, `test_end_to_end_with_sdk`

---

## E4 Processing and results

### SK-9 One label per minute
**As a** clinic reviewer, **I want** one result per 60-second window, labelled `stressed`, `not_stressed` or `na`, **so that** I can see when during the session stress happened.

Must · 5 points · Done

- **Given** a processed recording, **when** the app calls `GET /v1/results?device_id=`, **then** it gets one item per full 60-second window, oldest first.
- A trailing window shorter than 60 seconds is ignored.
- Each item has `window_start`, `label`, `heart_rate_bpm`, `signal_quality` and `model_version`.
- With the mock model, a simulated calm recording (68 bpm) is labelled `not_stressed` and a stressed one (105 bpm) is labelled `stressed`. Estimated heart rate is within 5 bpm of the simulated rate.

Evidence: `test_end_to_end_with_sdk`, `test_heart_rate_is_close_to_simulated`, `test_partial_window_is_ignored`

### SK-10 Say "not available" instead of guessing
**As a** wearer, **I want** minutes with too much movement or a poor signal to be marked `na`, **so that** I am never told I was stressed because I was walking.

Must · 3 points · Done

- **Given** a window where the wrist moved too much (accelerometer variation above the threshold), **then** `label = na`, `heart_rate_bpm = null`, `signal_quality = motion`.
- **Given** a flat or unusable pulse signal, **then** `label = na` and `signal_quality = poor_signal`.

Evidence: `test_end_to_end_with_sdk` (moving scenario), `test_flat_ppg_is_poor_signal`

### SK-11 Know when processing is finished
**As a** customer developer, **I want** to read the upload's status, **so that** my app knows when to fetch results or show an error.

Must · 2 points · Done

- `GET /v1/uploads/{id}` returns `pending_upload`, `processing`, `processed` or `failed`.
- **Given** a file that cannot be parsed, **then** the upload becomes `failed` with the reason in `error`, and no results are written.
- Re-running processing for the same upload overwrites its results; it never duplicates them.

Evidence: `test_bad_file_marks_upload_failed`, `test_end_to_end_with_sdk`

### SK-12 Trace every result
**As a** product owner, **I want** each result to carry the model version and signal quality, **so that** when a customer questions a label we can say which model, data quality and firmware produced it.

Must · 1 point · Done

- Every result includes `model_version` and `signal_quality`.
- The device behind each result has its `firmware_version` stored (see SK-4, SK-5).

Evidence: `test_end_to_end_with_sdk`

---

## E5 Developer experience

### SK-13 Errors a program can act on
**As a** customer developer, **I want** every error in the same machine-readable shape, **so that** my app can handle them in one place.

Must · 2 points · Done

- Every 4xx and 5xx answer is `application/problem+json` with `type`, `title`, `status` and `detail`.
- The SDK raises `StressKitError` carrying the status and the problem body.

Evidence: `test_wrong_secret_is_401_problem_json`, `test_bad_device_id_is_422_problem`, `test_sdk_raises_problem_details`

### SK-14 A published, versioned contract
**As a** customer developer, **I want** the API published as OpenAPI under `/v1`, **so that** I can generate clients and trust that v1 will not change under me.

Must · 2 points · Done

- `docs/openapi.json` matches the running code; CI fails if they drift.
- All paths start with `/v1`. A breaking change goes to `/v2` while `/v1` keeps working.
- Interactive docs are served at `/docs`.

Evidence: `test_committed_contract_matches_code`

### SK-15 Upload in one line
**As a** customer developer, **I want** one SDK call that does the whole upload, **so that** I don't have to learn the three-call flow to get started.

Must · 3 points · Done

- `client.upload_recording(device_id, recording, started_at)` creates the upload, sends the file and calls `/complete`.
- The SDK gets and refreshes tokens on its own, a minute before they expire.
- The SDK retries network errors, `429` and `5xx` up to 3 times, reusing the same `Idempotency-Key`.
- `wait_until_processed()` and `get_results()` cover the rest of the flow.

Evidence: `test_end_to_end_with_sdk`; retries checked by reading `client.py` (no automated test yet, see SK-18)

### SK-16 Try it in ten minutes
**As a** customer developer (or interviewer), **I want** a narrated demo that runs with no cloud account, **so that** I can see the whole flow before writing code.

Should · 1 point · Done

- Following the README, `pytest -q` and `python scripts/demo.py` run on Python 3.11+ on Windows, macOS and Linux.
- The demo prints every HTTP call and ends with a per-minute results table.

Evidence: CI runs the demo on Python 3.11 and 3.13

---

## E6 SDK robustness (milestone 3)

### SK-17 Keep recordings while offline
**As a** wearer, **I want** recordings made without a network to upload later on their own, **so that** no session is lost on a flight or in a basement.

Must · 5 points · Planned (M3)

- **Given** no network, **when** a recording is uploaded, **then** the SDK saves it to a local queue and returns a pending reference instead of failing.
- **When** the network returns, queued recordings upload oldest first, each with its original `Idempotency-Key`.
- The queue survives an app restart. When it reaches its size limit (default 50 MB), the app is told; nothing is dropped silently.

### SK-18 Prove retries are safe
**As an** operations engineer, **I want** automated tests that simulate dropped replies and server errors, **so that** we know retries never create duplicates.

Should · 2 points · Planned (M3)

- A test drops the reply to `POST /v1/uploads`, lets the SDK retry, and finds exactly one upload.
- A test returns `503` twice, then success, and the SDK succeeds without raising.
- A test returns `503` four times and the SDK raises `StressKitError` with status 503.

### SK-19 Upload long sessions in parts
**As a** customer developer, **I want** sessions longer than 30 minutes to upload in parts, **so that** a dropped connection does not restart a large upload.

Could · 8 points · Planned (M3)

- Files above 5 MB are sent in parts; a failed part is retried alone.
- Results are the same as for a single-part upload of the same data.

### SK-20 Install the SDK as a package
**As a** customer developer, **I want** to `pip install` a versioned SDK, **so that** I can pin and upgrade it like any other dependency.

Should · 2 points · Planned (M3)

- A tagged release builds a wheel; the version follows semantic versioning.
- A changelog lists changes per version.

---

## E7 Run on AWS (milestones 4 and 5)

All E7 stories share these acceptance criteria: the v1 contract and every existing test still pass against the deployed API; the region is ap-southeast-7 unless a required service is missing there; no secret is committed; only serverless, pay-per-use services (no EC2, RDS or NAT gateway).

### SK-21 Store raw files in S3
**As an** operations engineer, **I want** recordings in an encrypted S3 bucket with one prefix per tenant, **so that** storage is durable, cheap and separated by customer.

Must · 3 points · Planned (M4)

- `upload_url` is an S3 pre-signed PUT URL valid for 15 minutes, for exactly one key `tenant/device/upload.json`.
- The bucket blocks public access and encrypts at rest; objects move to cheaper storage after 30 days.
- A changed or expired URL is refused by S3 (`403`).

### SK-22 Store records in DynamoDB
**As an** operations engineer, **I want** devices, uploads and results in DynamoDB keyed by tenant first, **so that** lookups are fast and one tenant's query can never return another's items.

Must · 3 points · Planned (M4)

- Partition keys begin with `TENANT#<tenant_id>`. Results use sort key `RESULT#<window_start>`, so reprocessing overwrites.
- Idempotency keys are stored with a time-to-live of 24 hours.
- On-demand capacity; point-in-time recovery on.

### SK-23 Least-privilege access
**As an** operations engineer, **I want** each function to have only the permissions it needs, **so that** a bug in one part cannot read or change everything.

Must · 2 points · Planned (M4)

- The API function can write upload records and create pre-signed URLs, but cannot read raw files.
- The worker can read raw files and write results, but cannot issue tokens.
- Signing keys are read from SSM Parameter Store at start-up, not from code or plain environment variables.

### SK-24 Serve the API from API Gateway and Lambda
**As a** customer developer, **I want** the same API at a public HTTPS address, **so that** my app works the same as against the laptop version.

Must · 5 points · Planned (M5)

- `scripts/demo.py --base-url <api url>` passes end to end.
- p95 latency below 1 second for every call except the file upload.
- Throttling is set (for example 20 requests a second per client) so a runaway client cannot run up costs.

### SK-25 Process through a queue with a dead-letter queue
**As an** operations engineer, **I want** `/complete` to put a message on SQS and a worker Lambda to process it, **so that** spikes queue up instead of failing, and broken files are set aside.

Must · 5 points · Planned (M5)

- p95 time from `/complete` to `processed` is under 30 seconds for a 2-minute recording.
- A message that fails 3 times goes to the dead-letter queue and the upload becomes `failed`.
- Processing the same message twice leaves one set of results.

### SK-26 Deploy with one command
**As an** operations engineer, **I want** the whole stack defined in a SAM template, **so that** it can be created and deleted in one command and reviewed as code.

Should · 3 points · Planned (M5)

- `sam deploy` creates everything; `sam delete` removes everything with no leftovers that cost money.
- Every resource is tagged `project=stresskit-demo`.

---

## E8 Notify and operate (milestone 6)

### SK-27 Webhook when results are ready
**As a** customer developer, **I want** a signed webhook when an upload is processed or failed, **so that** my app doesn't have to poll.

Should · 5 points · Planned (M6)

- A tenant can register one HTTPS webhook URL and gets a signing secret.
- Each event (`upload.processed`, `upload.failed`) carries `upload_id`, `device_id`, status and a timestamp, signed with HMAC-SHA256 in a header.
- Failed deliveries retry with back-off for up to 24 hours. Events can arrive more than once; each has a unique `event_id`.

### SK-28 See failures before customers do
**As an** operations engineer, **I want** a dashboard and alarms, **so that** I know about failed uploads, slow processing or a filling dead-letter queue.

Should · 3 points · Planned (M6)

- The dashboard shows uploads per hour, processing time p95, error rate by status code and the share of `na` windows.
- Alarms by email: any message in the dead-letter queue; 5xx rate above 1% for 5 minutes; processing p95 above 30 s.
- Logs are JSON with `tenant_id`, `upload_id` and a request ID, and contain no raw signal data.

### SK-29 Keep the demo's cost capped
**As the** account owner, **I want** spend alerts and a cost review, **so that** the demo never surprises me with a bill.

Must · 1 point · Planned (M6)

- Budgets alert at $1, $5 and $10 a month (already set on the account).
- A cost note in `docs/` estimates monthly cost at 0, 1,000 and 100,000 uploads.
- Idle cost is close to zero: no always-on compute.

---

## Later (not scheduled)

| ID | Story | Why it is parked |
|---|---|---|
| SK-30 | As a clinic reviewer, I want results filtered by date range and paged, so that long histories load quickly | `limit` covers the demo; add `from`, `to` and a cursor before real customers |
| SK-31 | As a wearer, I want my data deleted on request, so that I control my health data (PDPA right to erasure) | Needed for production; design with S3 prefixes and DynamoDB keys already allows deleting by tenant and device |
| SK-32 | As a customer, I want to rotate my client secret without downtime | Needs two active secrets per client |
| SK-33 | As a product owner, I want to run a new model version on old recordings and compare, so that model upgrades are measured before release | Raw data is already kept for this; needs a reprocessing job and a comparison report |
| SK-34 | As a customer developer, I want SDKs for Kotlin and Swift | Python is enough to demonstrate the contract |
