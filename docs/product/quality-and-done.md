# Quality targets, Definition of Ready and Definition of Done

## Non-functional requirements

| ID | Area | Target | Why |
|---|---|---|---|
| NFR1 | Speed | API p95 under 1 s, file upload excluded | The app must never feel stuck waiting for the cloud |
| NFR2 | Freshness | Upload to result p95 under 30 s for a 2-minute recording | Near-real-time feedback after a session |
| NFR3 | Reliability | Upload success rate above 99.5% | Phones lose network; lost sessions erode trust fast |
| NFR4 | Privacy | No tenant can read or detect another's data | Health data; contractual and PDPA obligation |
| NFR5 | Security | TLS in transit, encryption at rest, tokens expire in 1 hour | Baseline for health data |
| NFR6 | Secrets | No secret in code or the repo; production keys in SSM | The repo is public |
| NFR7 | Cost | Idle near $0; demo month under $5 | Personal AWS account on the Paid plan, budgets at $1, $5 and $10 |
| NFR8 | Operability | Every failed upload is visible to the customer (`failed` status) and to us (alarm) | Silent failure is the worst failure |

The demo is **not a medical device**. A real product would add IEC 62304 software lifecycle, ISO 13485 quality management, ISO 14971 risk management and Thai FDA registration; these are out of scope.

## Definition of Ready

A story is ready to start when:

- It follows "As a … I want … so that …" (a Feature) or "As a … I need … so that …" (an Enabler) and names a persona from the [backlog](backlog.md).
- It has acceptance criteria that a test or a single manual check can prove.
- Any change to the API contract is written down (path, request, response, error codes).
- It fits in one milestone; if it is 8 points or more, consider splitting it.
- Its Type (Feature or Enabler) and its Depends on list are filled in, and those stories are done or planned earlier.
- Every acceptance criterion is written as Given / When / Then.

## Definition of Done

A story is done when:

- All acceptance criteria pass, and the story's Evidence line names a test or a "Manual check" for every criterion.
- `ruff check`, `ruff format --check` and `pytest` pass in CI on Python 3.11 and 3.13.
- `docs/openapi.json` is regenerated if the contract changed, and the change is backwards compatible within `/v1`.
- The README, this folder and the [traceability matrix](traceability.md) are updated.
- No secrets, personal data or real recordings are committed.
- For AWS stories: deployed with SAM, checked against the AWS URL, the AWS column in the traceability matrix filled in, and the cost after one day checked in the billing console.
