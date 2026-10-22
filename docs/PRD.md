# StressKit: one-page product brief

A demo product, built to show how a wearable health feature works end to end. Not a medical device.

## Problem

A clinic or corporate-wellness customer wants to know when their users are under stress, without building sensor processing or cloud infrastructure themselves.

## Users

| Who | Needs |
|---|---|
| Customer developer | An SDK and a clear API to send wearable data and get stress results back |
| Customer's end user (wears the watch) | Battery life, privacy, results that make sense |
| Our operations team | Know when uploads fail, keep cost low, keep tenants apart |

## What it does

1. The watch records PPG (pulse) and accelerometer data at 25 Hz.
2. The customer's app uses the SDK to upload a recording to the cloud.
3. The cloud splits it into 60-second windows and labels each one `stressed`, `not_stressed` or `na` (not enough signal quality, for example during motion).
4. The customer reads results through the API (later, gets a webhook when they are ready).

## Requirements

| # | Requirement | Why |
|---|---|---|
| R1 | Every call is authenticated per customer (tenant) | Health data; one customer must never see another's |
| R2 | Large files never pass through the API itself | Cost, speed, Lambda's 6 MB payload limit |
| R3 | A retried upload never creates a duplicate | Phones lose network all the time |
| R4 | Processing is asynchronous; the API answers in under a second | Model run time must not block the app |
| R5 | Each result carries signal quality and model version | Traceability, and an honest `na` beats a wrong label |
| R6 | Errors are machine-readable (RFC 9457 problem details) | SDKs and support can act on them |
| R7 | The API contract is versioned (`/v1`) and published as OpenAPI | Customers integrate against a stable contract |

## Success metrics (for a real product)

- Upload success rate above 99.5%; time from upload to result p95 under 30 s.
- Share of windows labelled `na` (too high means the motion gate or the sensor needs work).
- Integration time for a new customer developer (target: one day with the SDK).

## Out of scope for the demo

A real stress model (the mock uses heart rate only), firmware and Bluetooth, mobile apps, medical certification (IEC 62304, ISO 13485, Thai FDA), billing.

## Milestones

User stories, acceptance criteria and the requirement-to-test matrix are in [`docs/product/`](product/README.md).

| # | Milestone | Status |
|---|---|---|
| 1 | Repo layout, mock wearable, local API running | Done |
| 2 | API contract: auth, devices, uploads, results, errors, idempotency, OpenAPI | Done |
| 3 | SDK polish: offline buffer, chunked uploads, packaged release | Next |
| 4 | AWS storage: S3 pre-signed URLs, DynamoDB tables, IAM roles | |
| 5 | AWS compute: API Gateway + Lambda, SQS queue + worker Lambda + DLQ, SAM deploy | |
| 6 | Webhooks, CloudWatch dashboard and alarms, cost review | |
