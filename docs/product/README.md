# Product documents

How StressKit is planned and checked, from the product owner's side. The [product brief](../PRD.md) says why; these files say what, in what order, and how we know it works.

| File | What it holds | Use it to |
|---|---|---|
| [backlog.md](backlog.md) | Personas, 8 epics, 34 user stories with acceptance criteria, status and evidence | Plan a milestone; explain a feature in user terms |
| [traceability.md](traceability.md) | Requirements and quality targets → stories → tests, with an empty AWS column | Cross-check each AWS milestone against what already works locally |
| [quality-and-done.md](quality-and-done.md) | Non-functional targets, Definition of Ready, Definition of Done | Decide whether a story can start, and whether it is finished |
| [decisions.md](decisions.md) | Why the main design choices were made, and open questions | Answer "why did you do it this way?" |

## Where things stand

| Milestone | Stories | Status |
|---|---|---|
| 1–2 Local API, contract, SDK, mock model | SK-1 to SK-4, SK-6 to SK-16 | Done, 23 tests |
| 3 SDK robustness | SK-17 to SK-20 | Next |
| 4 AWS storage (S3, DynamoDB, IAM) | SK-21 to SK-23 | Planned |
| 5 AWS compute (API Gateway, Lambda, SQS, SAM) | SK-24 to SK-26 | Planned |
| 6 Webhooks, monitoring, cost | SK-27 to SK-29 | Planned |
| Later | SK-5, SK-30 to SK-34 | Not scheduled |

## How to cross-check a milestone

1. Pick the milestone's stories in the backlog and read each acceptance criterion.
2. Run the existing tests locally (`pytest -q`); everything already marked Done must stay green.
3. For AWS milestones, run the demo and the tests against the deployed URL, then fill in the AWS column in the traceability matrix.
4. Update each story's status, and add a decision to the log if something changed from the plan.
