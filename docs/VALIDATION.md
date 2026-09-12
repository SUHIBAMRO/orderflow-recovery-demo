# Validation record

Executed on 2026-09-12 in the creation workspace, Python 3.11+ compatible standard-library mode.

| Check | Actual result |
|---|---|
| `python -m unittest discover -s tests -v` | **25 tests passed** (20 domain/persistence + 5 real-HTTP integration) |
| `python -m compileall -q orderflow scripts tests` | Passed |
| `node --check web/app.js` | Passed |
| API authentication and viewer write restrictions | Passed over HTTP |
| Owner-data correction end-to-end | Passed over HTTP, preserving policy reference |
| Operator refund denied; supervisor allowed | Passed over HTTP |
| Concurrent duplicate order creation | Passed using SQLite verification backend |
| Concurrent ticks / successful effects not duplicated | Passed using SQLite verification backend |
| Lost insurer acknowledgement | Passed against durable simulator ledger |
| Crash after provider effect, before local commit | Passed via injected exception and fresh DB/engine instances |
| Pending retry deadline survives engine restart | Passed |
| Full FastAPI + PostgreSQL + Temporal stack | **Not run: Docker/dependencies absent** |
| PostgreSQL row locks and advisory locks under load | **Not tested** |
| Actual Temporal worker-process restart | Script supplied; **not run** |
| Browser appearance and UI interaction | **Not verified: browser blocked local URL** |
| LLM classification accuracy | **Not applicable: no LLM integrated** |
| Real BJAK / insurer / JPJ / payment integration | **Not implemented** |

Portable tests validate the shared business logic, not SDK compatibility, cloud reliability, PostgreSQL performance or a production recovery guarantee. The end-to-end deployment smoke script deliberately fails if the actual stack cannot execute the scenarios. No throughput, cost saving, accuracy, fraud rate or latency benchmark is claimed.

## Before presenting it as a verified full-stack demo

1. Run `docker compose up --build -d` on a Docker-capable computer.
2. Run `python scripts/smoke_compose.py`; capture actual pass/fail output.
3. Exercise the UI on desktop and mobile. Check keyboard operation, error messages and stale-action conflicts.
4. Verify worker restart, provider timeout behavior and one persisted policy/refund effect per semantic key against the PostgreSQL ledger.
5. Pin a dependency lock and container digests for the tested environment.
6. Host only on an authorized environment with HTTPS and appropriate authentication; do not imply a private integration exists.
