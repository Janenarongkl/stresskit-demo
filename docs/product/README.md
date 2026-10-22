# Product documents

How StressKit is planned and checked, from the product owner's side. The [product brief](../PRD.md) says why; these files say what, in what order, and how we know it works.

| File | What it holds | Use it to |
|---|---|---|
| [backlog.md](backlog.md) | Personas, 8 epics, 34 stories (features and enablers) with Given/When/Then criteria, dependencies, milestone load and evidence | Plan a milestone; explain a feature in user terms |
| [traceability.md](traceability.md) | Requirements and quality targets → stories → tests, with an empty AWS column | Cross-check each AWS milestone against what already works locally |
| [quality-and-done.md](quality-and-done.md) | Non-functional targets, Definition of Ready, Definition of Done | Decide whether a story can start, and whether it is finished |
| [../cost.md](../cost.md) | Monthly cost at 0, 1,000 and 100,000 uploads | Show the demo cannot run up a bill |
| [../aws/deploy-m4.md](../aws/deploy-m4.md) | Deploy, check and remove the milestone 4 stack | Do the AWS cross-check |
| [decisions.md](decisions.md) | Why the main design choices were made, and open questions | Answer "why did you do it this way?" |

## Where things stand

| Milestone | Stories | Points | Status |
|---|---|---|---|
| 1–2 Local API, contract, SDK, mock model | SK-1 to SK-4, SK-6 to SK-16 | 39 | Done |
| 3 SDK and traceability | SK-18, SK-20, SK-5, SK-17 | 12 | Done (54 tests) |
| 4 AWS foundations (cost guardrails, SAM, S3, DynamoDB, IAM) | SK-29, SK-26, SK-21, SK-22, SK-23 | 12 | Built (74 tests); deploy check pending |
| 5 AWS compute (API Gateway, Lambda, SQS) | SK-24, SK-25 | 10 | Next |
| 6 Webhooks and monitoring | SK-28, SK-27 | 8 | Planned |
| Later | SK-19, SK-30 to SK-34 | | Not scheduled |

The backlog also has the dependency graph and the milestone 3 ranking (WSJF).

## How to cross-check a milestone

1. Pick the milestone's stories in the backlog and read each acceptance criterion.
2. Run the existing tests locally (`pytest -q`); everything already marked Done must stay green.
3. For AWS milestones, run the demo and the tests against the deployed URL, then fill in the AWS column in the traceability matrix.
4. Update each story's status, and add a decision to the log if something changed from the plan.
