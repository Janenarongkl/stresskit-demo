# Traceability: requirements → stories → evidence

Use this to cross-check each milestone. The **Local** column is proven today by the tests named. The **AWS** column is empty on purpose: fill it in (✅, ❌ or a note) when milestones 4 to 6 are deployed, by running the same check against the AWS URL.

Requirements R1 to R7 come from the [product brief](../PRD.md). NFR1 to NFR8 are in [quality and done](quality-and-done.md).

## Requirements

| Req | Requirement | Stories | Local evidence | AWS check (how) | AWS |
|---|---|---|---|---|---|
| R1 | Every call is authenticated per tenant | SK-1, SK-2, SK-3, SK-23 | `test_auth.py` (6 tests), `test_tenant_isolation` | Run `pytest` against the AWS URL; call with Clinic B's token for Clinic A's device and expect 404 | |
| R2 | Large files never pass through the API | SK-6, SK-21 | `test_upload_url_is_for_one_file_and_expires_in_15_minutes`, `test_tampered_or_expired_upload_url_is_403`, `test_file_over_size_limit_is_413` | `upload_url` host is `*.s3.ap-southeast-7.amazonaws.com`; API Gateway logs show no request bodies over 10 KB | |
| R3 | A retried upload never creates a duplicate | SK-7, SK-8, SK-15, SK-18, SK-22 | `test_idempotency_key_replays_same_upload`, `test_idempotency_key_with_different_body_is_409`, `test_complete_twice_queues_processing_once`, `test_sdk_retries_server_errors_then_succeeds` | Same tests against AWS; DynamoDB has one `UPLOAD#` item per key | |
| R4 | Processing is async; the API answers in under a second | SK-8, SK-11, SK-24, SK-25 | `/complete` returns 202 before processing (`test_end_to_end_with_sdk`) | CloudWatch: API p95 under 1 s; `/complete` → `processed` p95 under 30 s | |
| R5 | Each result carries signal quality and model version (firmware via the upload, SK-5) | SK-5, SK-9, SK-10, SK-12 | `test_end_to_end_with_sdk`, `test_flat_ppg_is_poor_signal`; firmware: planned in M3 | Read results from DynamoDB; every item has both fields | |
| R6 | Errors are machine-readable (RFC 9457) | SK-13 | `test_wrong_secret_is_401_problem_json`, `test_bad_device_id_is_422_problem`, `test_file_over_size_limit_is_413`, `test_sdk_raises_problem_details` | Check that API Gateway's own errors (throttling `429`, missing route `404`) are also problem+json, or document the exception | |
| R7 | Versioned contract published as OpenAPI | SK-14 | `test_committed_contract_matches_code` | `GET <aws>/openapi.json` equals `docs/openapi.json` | |

## Non-functional requirements

| NFR | Target | Stories | Local evidence | AWS check (how) | AWS |
|---|---|---|---|---|---|
| NFR1 | API latency p95 < 1 s (excluding file upload) | SK-24 | Not measured locally | CloudWatch `Latency` p95 on the HTTP API | |
| NFR2 | Upload → result p95 < 30 s for 2 minutes of data | SK-25 | Demo finishes in about a second | CloudWatch metric from worker logs | |
| NFR3 | Upload success rate > 99.5% | SK-7, SK-17, SK-25 | Not measured | Dashboard: processed ÷ created per day | |
| NFR4 | No tenant can read another's data | SK-3, SK-22, SK-23 | `test_tenant_isolation` | Tests + review that IAM policies and keys always include the tenant | |
| NFR5 | Encrypted in transit and at rest | SK-21, SK-22 | Local runs over HTTP (laptop only) | HTTPS only on API Gateway; S3 and DynamoDB encryption on | |
| NFR6 | No secret in the repository | SK-23 | Demo values are labelled as public and overridable by env | Secret scanning on the repo; keys in SSM | |
| NFR7 | Idle cost close to $0; demo month under $5 | SK-29, SK-26 | Budgets at $1, $5, $10 set on 21 Oct 2026 | AWS Budgets and Cost Explorer after one week | |
| NFR8 | Every failure is visible | SK-11, SK-25, SK-28 | Upload becomes `failed` with `error` (`test_bad_file_marks_upload_failed`) | DLQ alarm fires on a broken file | |

## Test index

| Test | Stories |
|---|---|
| `test_token_has_tenant_claim` | SK-1 |
| `test_wrong_secret_is_401_problem_json` | SK-1, SK-13 |
| `test_unsupported_grant_type_is_422` | SK-1 |
| `test_missing_token_is_401` | SK-2 |
| `test_expired_token_is_401` | SK-2 |
| `test_token_signed_with_other_key_is_401` | SK-2 |
| `test_tenant_isolation` | SK-3, SK-4 |
| `test_duplicate_device_is_409` | SK-4 |
| `test_bad_device_id_is_422_problem` | SK-4, SK-13 |
| `test_upload_url_is_for_one_file_and_expires_in_15_minutes` | SK-6 |
| `test_tampered_or_expired_upload_url_is_403` | SK-6 |
| `test_file_over_size_limit_is_413` | SK-6, SK-13 |
| `test_duration_outside_one_minute_to_one_day_is_422` (59 s, 1 day + 1 s) | SK-6 |
| `test_idempotency_key_replays_same_upload` | SK-7 |
| `test_idempotency_key_with_different_body_is_409` | SK-7 |
| `test_idempotency_keys_are_per_tenant` | SK-7, SK-3 |
| `test_complete_before_file_is_409` | SK-8 |
| `test_complete_twice_queues_processing_once` | SK-8 |
| `test_end_to_end_with_sdk` (calm, stressed, moving) | SK-4, SK-6, SK-8, SK-9, SK-10, SK-11, SK-12, SK-15 |
| `test_heart_rate_is_close_to_simulated` (calm, stressed) | SK-9 |
| `test_partial_window_is_ignored` | SK-9 |
| `test_results_limit_outside_1_to_1440_is_422` (0, 1441) | SK-9 |
| `test_flat_ppg_is_poor_signal` | SK-10, SK-12 |
| `test_only_moving_minutes_are_na` | SK-10 |
| `test_bad_file_marks_upload_failed` | SK-11 |
| `test_reprocessing_overwrites_results` | SK-11 |
| `test_sdk_raises_problem_details` | SK-13 |
| `test_committed_contract_matches_code` | SK-14 |
| `test_sdk_reuses_token_and_refreshes_before_expiry` | SK-15 |
| `test_sdk_retries_server_errors_then_succeeds` | SK-15 |
| `test_sdk_gives_up_after_three_retries` | SK-15 |

36 test cases in total, counting each parameter. Criteria checked by hand instead of a test are marked "Manual check" in the backlog (SK-3, SK-7, SK-12, SK-14, SK-16). NFR1 to NFR3 can only be measured once deployed.
