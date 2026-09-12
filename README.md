# OrderFlow Recovery

A working synthetic insurance order-recovery prototype. It detects where a multi-step order failed, applies explicit recovery rules, performs bounded retries, routes human actions, prevents duplicate side effects, and preserves an audit trail.

## Live demo

Open the public sandbox: **https://orderflow-public-demo-production.up.railway.app/**

No installation or access token is required. English is the default language; select **NL** in the header for Dutch. All customers, policies, payments, provider responses, and refunds are synthetic. Never enter real personal information.

## What is implemented

- Persistent workflow state and append-only application audit events
- Synthetic payment, insurer, JPJ, and notification HTTP APIs
- Explicit recovery rules for data mismatch, missing photos, blacklist, timeouts, and unknown responses
- Bounded retry timing and retry-budget exhaustion
- Idempotency keys that prevent duplicate policy issuance and refunds
- Version-checked operator actions and role-gated refunds
- Operations console, scenario lab, and recovery-rule reference
- English and Dutch user interface

The public deployment uses SQLite and local synthetic provider APIs. The repository also includes a production-oriented FastAPI, PostgreSQL, and Temporal configuration. External BJAK, insurer, JPJ, payment, and notification integrations are not included.

## Run locally

Python 3.11 or newer is required.

```sh
python scripts/setup_env.py
python scripts/run_local.py
```

Open `http://127.0.0.1:8080` on the same computer. Copy the appropriate role token from the locally generated `.env` file. The operator role can resolve standard exceptions; the supervisor role can approve synthetic roadtax refunds.

This lightweight mode stores data in `data/` and does not run Temporal. Stop it with `Ctrl+C`.

## Run the full stack

Docker with Compose v2 is required.

```sh
python scripts/setup_env.py
docker compose up --build -d
python scripts/smoke_compose.py
```

The full stack runs FastAPI, PostgreSQL, Temporal, a worker, and synthetic provider services. Stop the containers while preserving volumes with:

```sh
docker compose down
```

## Recommended demo walkthrough

1. Open **Scenario lab** and run **Owner data mismatch**.
2. Return to the queue and inspect why the roadtax step stopped.
3. Select **Correct & continue**, enter four synthetic digits, and record an audit note.
4. Observe the same workflow resume and complete without reissuing the policy.
5. Run **Temporary insurer outage** to observe bounded retries and recovery.
6. Run **Lost acknowledgement** to see idempotent reconciliation return the existing policy.
7. Run **Blacklist → refund** to demonstrate explicit approval of a roadtax-only synthetic refund.

## Verification

```sh
python -m unittest discover -s tests -v
python -m compileall -q orderflow scripts tests
node --check web/app.js
```

The suite contains 25 tests covering workflow recovery, HTTP behavior, authorization, idempotency, restart recovery, duplicate callbacks, and refund safety. See `docs/VALIDATION.md` for the verification boundary and `docs/ARCHITECTURE.md` for the architecture and limitations.

## API summary

| Endpoint | Purpose |
|---|---|
| `GET /api/session` | Return the current role and runtime mode |
| `GET /api/orders` | List persisted synthetic orders |
| `POST /api/orders` | Create an idempotent synthetic order |
| `GET /api/orders/{id}` | Return an order and its audit events |
| `POST /api/orders/{id}/actions/{action}` | Execute a version-checked operator command |
| `POST /api/classify` | Run read-only deterministic text interpretation |
| `GET /healthz` | Report API and database readiness |

This is an independent portfolio prototype. It is not a BJAK product, approved integration, compliance certification, or legal statement of BJAK or JPJ policy.
