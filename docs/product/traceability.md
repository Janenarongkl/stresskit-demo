# Traceability: requirements → stories → evidence

Use this to cross-check each milestone. The **Local** column is proven today by the tests named. The **AWS** column is empty on purpose: fill it in (✅, ❌ or a note) when milestones 4 to 6 are deployed, by running the same check against the AWS URL.

Milestone 4 adds a middle step: the same API runs on S3 and DynamoDB against moto, a local stand-in for AWS (`tests/test_aws_backend.py`, `tests/test_template.py`). Those tests are listed under **Local evidence**. The AWS column is still for checks against the real account, done with [deploy-m4.md](../aws/deploy-m4.md).

Requirements R1 to R7 come from the [product brief](../PRD.md). NFR1 to NFR8 are in [quality and done](quality-and-done.md).

## Requirements

| Req | Requirement | Stories | Local evidence | AWS check (how) | AWS |
|---|---|---|---|---|---|
| R1 | Every call is authenticated per tenant | SK-1, SK-2, SK-3, SK-23 | `test_auth.py` (6 tests), `test_tenant_isolation`; on S3 + DynamoDB: `test_other_tenant_cannot_see_device_upload_or_results` | Run `pytest` against the AWS URL; call with Clinic B's token for Clinic A's device and expect 404 | |
| R2 | Large files never pass through the API | SK-6, SK-21 | `test_upload_url_is_for_one_file_and_expires_in_15_minutes`, `test_tampered_or_expired_upload_url_is_403`, `test_file_over_size_limit_is_413`; on S3: `test_upload_link_is_s3_scoped_to_one_file_and_short_lived`, `test_oversize_file_in_s3_is_marked_failed` | `upload_url` host is `*.s3.ap-southeast-7.amazonaws.com`; API Gateway logs show no request bodies over 10 KB | |
| R3 | A retried upload never creates a duplicate | SK-7, SK-8, SK-15, SK-18, SK-22 | `test_idempotency_key_replays_same_upload`, `test_idempotency_key_with_different_body_is_409`, `test_complete_twice_queues_processing_once`, `test_sdk_retries_server_errors_then_succeeds`, `test_lost_reply_to_create_upload_gives_one_upload`, `test_network_error_on_complete_queues_processing_once`; on DynamoDB: `test_idempotency_key_replays_then_expires` | Same tests against AWS; DynamoDB has one `UPLOAD#` item per key | |
| R4 | Processing is async; the API answers in under a second | SK-8, SK-11, SK-24, SK-25 | `/complete` returns 202 before processing (`test_end_to_end_with_sdk`) | CloudWatch: API p95 under 1 s; `/complete` → `processed` p95 under 30 s | |
| R5 | Each result carries signal quality and model version (firmware via the upload, SK-5) | SK-5, SK-9, SK-10, SK-12 | `test_end_to_end_with_sdk`, `test_flat_ppg_is_poor_signal`, `test_uploads_keep_the_firmware_they_were_recorded_with` | Read results from DynamoDB; every item has both fields | |
| R6 | Errors are machine-readable (RFC 9457) | SK-13 | `test_wrong_secret_is_401_problem_json`, `test_bad_device_id_is_422_problem`, `test_file_over_size_limit_is_413`, `test_sdk_raises_problem_details` | Check that API Gateway's own errors (throttling `429`, missing route `404`) are also problem+json, or document the exception | |
| R7 | Versioned contract published as OpenAPI | SK-14 | `test_committed_contract_matches_code` | `GET <aws>/openapi.json` equals `docs/openapi.json` | |

## Non-functional requirements

| NFR | Target | Stories | Local evidence | AWS check (how) | AWS |
|---|---|---|---|---|---|
| NFR1 | API latency p95 < 1 s (excluding file upload) | SK-24 | Not measured locally | CloudWatch `Latency` p95 on the HTTP API | |
| NFR2 | Upload → result p95 < 30 s for 2 minutes of data | SK-25 | Demo finishes in about a second | CloudWatch metric from worker logs | |
| NFR3 | Upload success rate > 99.5% | SK-7, SK-17, SK-25 | Not measured | Dashboard: processed ÷ created per day | |
| NFR4 | No tenant can read another's data | SK-3, SK-22, SK-23 | `test_tenant_isolation`; `test_every_item_is_keyed_by_tenant`, `test_api_cannot_read_recordings_and_worker_cannot_read_secrets` | Tests + review that IAM policies and keys always include the tenant | |
| NFR5 | Encrypted in transit and at rest | SK-21, SK-22 | Local runs over HTTP (laptop only); template: `test_bucket_is_private_encrypted_and_https_only` | HTTPS only on API Gateway; S3 and DynamoDB encryption on | |
| NFR6 | No secret in the repository | SK-23 | Demo values are labelled as public and overridable by env; `test_secrets_are_read_from_ssm` | Secret scanning on the repo; keys in SSM | |
| NFR7 | Idle cost close to $0; demo month under $5 | SK-29, SK-26 | Budgets at $1, $5, $10 set on 21 Oct 2026; [cost.md](../cost.md), `test_no_always_on_compute` | AWS Budgets and Cost Explorer after one week | |
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
| `test_patch_records_a_firmware_upgrade` | SK-5 |
| `test_uploads_keep_the_firmware_they_were_recorded_with` | SK-5 |
| `test_patch_unknown_or_other_tenants_device_is_404` | SK-5 |
| `test_result_leads_to_firmware_through_its_upload` | SK-5 |
| `test_lost_reply_to_create_upload_gives_one_upload` | SK-18 |
| `test_network_error_on_complete_queues_processing_once` | SK-18 |
| `test_retry_after_is_respected` | SK-18 |
| `test_client_errors_are_not_retried` | SK-18 |
| `test_401_on_a_cached_token_gets_one_fresh_token` | SK-18 |
| `test_offline_upload_is_queued_and_sent_when_back_online` | SK-17 |
| `test_queue_drains_oldest_first` | SK-17 |
| `test_queue_survives_an_app_restart` | SK-17 |
| `test_full_queue_raises_and_keeps_what_it_has` | SK-17 |
| `test_token_expired_while_offline_does_not_fail_the_drain` | SK-17 |
| `test_expired_upload_link_is_renewed_with_the_same_key` | SK-17 |
| `test_refused_recording_is_set_aside_and_the_rest_continue` | SK-17 |
| `test_replay_after_the_file_arrived_has_no_link` | SK-7, SK-17 |
| `test_sdk_version_matches_its_package_metadata` | SK-20 |
| `test_sdk_end_to_end_on_s3_and_dynamodb` | SK-21, SK-22 |
| `test_upload_link_is_s3_scoped_to_one_file_and_short_lived` | SK-21 |
| `test_complete_before_the_file_is_in_s3_is_409` | SK-21, SK-8 |
| `test_local_blob_route_is_off_on_aws` | SK-21 |
| `test_firmware_update_is_stored_in_dynamodb` | SK-22, SK-5 |
| `test_other_tenant_cannot_see_device_upload_or_results` | SK-22, SK-3 |
| `test_every_item_is_keyed_by_tenant` | SK-22 |
| `test_reprocessing_overwrites_results_in_dynamodb` | SK-22, SK-11 |
| `test_results_limit_returns_the_latest_windows_oldest_first` | SK-22, SK-9 |
| `test_idempotency_key_replays_then_expires` | SK-22, SK-7 |
| `test_secrets_are_read_from_ssm` | SK-23 |
| `test_missing_ssm_parameters_fail_at_startup` | SK-23 |
| `test_oversize_file_in_s3_is_marked_failed` | SK-21 |
| `test_bucket_is_private_encrypted_and_https_only` | SK-21 |
| `test_raw_recordings_expire` | SK-21 |
| `test_table_is_on_demand_with_ttl_and_backups` | SK-22 |
| `test_no_wildcard_actions_or_resources` | SK-23 |
| `test_api_cannot_read_recordings_and_worker_cannot_read_secrets` | SK-23 |
| `test_no_always_on_compute` | SK-29 |
| `test_every_resource_that_takes_tags_is_tagged` | SK-26 |

74 test cases in total, counting each parameter (20 of them for milestone 4). Criteria checked by hand instead of a test are marked "Manual check" in the backlog (SK-3, SK-7, SK-12, SK-14, SK-16, SK-20). NFR1 to NFR3 can only be measured once deployed.
