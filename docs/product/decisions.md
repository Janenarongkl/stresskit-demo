# Decision log

Short records of product and architecture decisions: what was chosen, what else was considered, and why. Add a new entry rather than editing an old one; mark replaced decisions as superseded.

| ID | Date | Decision | Alternatives considered | Why | Status |
|---|---|---|---|---|---|
| D1 | 2026-10-21 | Heart rate and stress are calculated in the cloud, not on the watch or phone | On-device model | Models can be improved and old data reprocessed without a firmware or app release; the watch saves battery | Accepted |
| D2 | 2026-10-21 | Customers authenticate with OAuth 2.0 client credentials and a 1-hour JWT that carries the tenant | API keys sent on every call; Amazon Cognito user pools | Standard machine-to-machine flow; the secret crosses the wire once; the tenant comes from a signed token, never from the request. Cognito can replace the issuer later without changing clients | Accepted |
| D3 | 2026-10-21 | Raw files go straight to storage through pre-signed URLs | Upload through the API | Keeps the API small and cheap; avoids Lambda's 6 MB payload limit (R2) | Accepted |
| D4 | 2026-10-21 | `Idempotency-Key` header on upload creation; replay returns the same upload, a changed body returns 409 | Detect duplicates by device and start time | Explicit, standard pattern (Stripe-style); handles retries without guessing (R3) | Accepted |
| D5 | 2026-10-21 | Processing is asynchronous: `/complete` returns 202 and the client polls (webhooks later) | Synchronous processing | Model time must not block the app; a queue absorbs spikes (R4) | Accepted |
| D6 | 2026-10-21 | Another tenant's resources return 404, not 403 | 403 Forbidden | 403 would confirm that the ID exists for someone else | Accepted |
| D7 | 2026-10-21 | Windows with too much movement are labelled `na`, not guessed | Always output a label | An honest "not available" protects trust; the share of `na` is itself a product metric | Accepted |
| D8 | 2026-10-21 | Errors use RFC 9457 problem details; the contract is versioned under `/v1` and published as OpenAPI with a drift test | Ad-hoc error bodies; unversioned paths | One error shape for every client; breaking changes go to `/v2` (R6, R7) | Accepted |
| D9 | 2026-10-21 | Results are keyed by window start, so reprocessing overwrites | Append-only results | Safe retries and reprocessing (SK-11, SK-25) | Accepted |
| D10 | 2026-10-21 | AWS region ap-southeast-7 (Thailand), serverless only | ap-southeast-1 (Singapore); containers on EC2 or ECS | Data stays in Thailand, a likely customer expectation for health data; serverless keeps idle cost near zero. Confirm that API Gateway, Lambda, SQS, S3 and DynamoDB are all available there before milestone 4 | Accepted, to verify |
| D11 | 2026-10-21 | The mock model uses a heart-rate threshold (above 90 bpm = stressed) | Heart-rate variability features; a trained classifier | The demo is about the system around the model. A real model would use HRV and skin temperature, trained on labelled data; the interface (`model_version`, `signal_quality`) already allows swapping it | Accepted for the demo |
| D12 | 2026-10-22 | Defer multipart upload (SK-19) out of milestone 3; add firmware traceability (SK-5) instead | Keep SK-19 in M3 | WSJF ranking: SK-19 scores 0.8 against 3.6 to 7.0 for the others. Demo recordings are about 105 KB, and M3 drops from 17 points to 12 | Accepted |
| D13 | 2026-10-22 | Infrastructure as code (SK-26) and cost guardrails (SK-29) come first in milestone 4, before any resource is created | SAM at the end of milestone 5; cost review in milestone 6 | Cost risk starts with the first deployed resource, and resources created by hand are easy to forget and hard to delete | Accepted |
| D14 | 2026-10-22 | On an `Idempotency-Key` replay after the file has arrived, `upload_url` and `upload_url_expires_at` are `null`. This is a contract change inside `/v1`, allowed only because the API is still 0.x with no external customers; from 1.0 such a change would go to `/v2` | Keep returning the first, expired link; issue a new link that could overwrite a processed file; a different response shape | A new link would let a retry replace a file that was already processed, and an expired one is never useful. The OpenAPI schema marks both fields nullable and the CHANGELOG flags it under Contract | Accepted |

## Open questions

| Question | Needed by | Notes |
|---|---|---|
| Are all five services available in ap-southeast-7? | Milestone 4 | If not, fall back to ap-southeast-1 and note the data-residency trade-off |
| How long do we keep raw recordings? | Milestone 4 | Proposal: 90 days, then delete; results kept longer. Affects SK-31 (deletion) and cost |
| Polling interval guidance for clients before webhooks exist | Milestone 3 | Proposal: every 2 s for 30 s, then back off |
