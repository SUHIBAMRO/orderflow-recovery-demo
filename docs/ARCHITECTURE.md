# OrderFlow Recovery — architecture and limits

## Scope

A synthetic insurance-order exception-handling prototype for an operations team. It is not affiliated with BJAK, JPJ, an insurer or a payment provider. Failure codes, prices, labels and policies are illustrative. It makes no claim about a company's private APIs, internal workflows, regulatory approval or actual integration feasibility.

The UI is an operations workspace, not a marketing dashboard. Counts are derived from persisted orders (the latest 500), not fabricated KPIs. Every scenario creates new backend state. There is no browser-only business-state store.

## Deployment components

| Component | Implementation | Responsibility |
|---|---|---|
| Operations UI | HTML, CSS, JavaScript, same origin as API | Queue, filters, evidence, actions, scenario creation |
| API | FastAPI | Auth, validation, reads, idempotent commands |
| Orders database | PostgreSQL 16 | Orders, events, action receipts, durable wakeup outbox |
| Orchestrator | Temporal Python workflow + worker | Durable timers, waits, activity recovery |
| Provider simulator | Separate FastAPI process | Synthetic payment, insurer, JPJ, refund, notification HTTP endpoints |
| Provider ledger | Independent transactions | Persist successful effects and return the same reference on repeated keys |
| Verification mode | Python stdlib HTTP + SQLite | Execute the same service and decision engine without deployment dependencies |

The four external domains share a single simulator process with distinct endpoints. They are not separate production services. Redis is deliberately unnecessary in this bounded implementation. No unneeded framework or queue is claimed.

## State and recovery

`PAYMENT → INSURER → ROADTAX → COMPLETED`

Branches:

- Photos required: `INSURER → NOTIFY_PHOTOS → WAITING_PHOTOS`. An operator confirms synthetic photo review and resumes `INSURER` with a new semantic revision. No file upload, image analysis or document authenticity check is implemented.
- Owner mismatch: `ROADTAX → WAITING_CORRECTION`. Enter corrected synthetic last-four digits, preserve the issued policy and resume roadtax. This is not real identity verification.
- Blacklist: `ROADTAX → REFUND_REQUIRED`. No automatic roadtax retry. A supervisor authorizes `REFUND → ROADTAX_REFUNDED`. Only integer roadtax cents are refunded; insurance is not cancelled.
- Timeout: reuse operation key; 2-second then 4-second backoff; after three attempts, `MANUAL_REVIEW`. A documented operator retry authorization permits another bounded cycle.
- Unknown/invalid outcome: `MANUAL_REVIEW`, not a guessed automated action.
- Escalation pauses the workflow; external investigation/resolution of escalated cases is outside this MVP.

## Transaction boundary and idempotency

One order is locked during each bounded HTTP attempt and its state/event commit. PostgreSQL uses row locks; SQLite verification mode uses `BEGIN IMMEDIATE` and therefore serializes writers. This is intentional for simplicity, not a high-throughput claim.

External effects cannot be atomically committed with the local database. The provider must honor a stable idempotency key. If the provider commits issuance but the response is lost, the next call returns the same reference. Tests also inject a crash after the remote effect but before the local transaction commit. This is **at-least-once execution with provider-side deduplication**, not universal exactly-once delivery.

Keys include the order, operation and semantic input revision. Attempt numbers never change the key. Confirmed photo receipt and corrected owner data use a new revision only for the affected step. Payload mismatch under an already-used successful provider key is rejected.

Order creation has a unique request key. Operator actions include an expected order version, a request key, an actor and an audit note. Duplicate identical commands return a saved receipt; stale or inconsistent commands fail. A role check precedes a duplicate refund receipt, so a lower-privilege user cannot reuse an elevated receipt.

The API writes a wakeup in the same transaction as a command. The worker reads this durable outbox and uses Temporal Signal-With-Start. It marks wakeups delivered only after successful dispatch. Duplicate wakeups are harmless. A waiting workflow also reconciles every 30 seconds. Temporal continues as new when history recommends it.

## Security posture

- Three distinct environment-provided tokens demonstrate viewer/operator/supervisor authorization.
- They are shared role identities, not individual-user accounts, SSO, MFA or expiring sessions. Actors are labeled accordingly.
- Browser tokens are kept in memory, not localStorage or cookies. The UI and API are same-origin; no permissive CORS is configured.
- All money uses integer cents and fixed MYR currency. Real card/bank details are not collected.
- Only synthetic identity suffixes are collected. Do not enter real names, identifiers or documents in this prototype.
- Provider calls are authenticated and stay inside the Compose network. The public UI port is bound to loopback only by default.
- Unknown provider responses fail closed into manual review.
- The UI escapes record/event content; scripts are external, with a restrictive Content Security Policy.
- Events have no edit/delete application endpoint. This is append-only application behavior, **not** cryptographic or administrator-proof immutability.
- Production deployment still needs individual identity, secret management, least-privilege DB accounts, TLS, rate limits, retention/erasure policy, approval separation, monitoring, backups, migration management and security review.

## Text classification

`POST /api/classify` is an explicitly labeled deterministic baseline. It returns a proposed category and a mandatory human-confirmation flag. It cannot issue a policy, approve a refund or mutate an order. **No LLM is integrated or evaluated.** A future LLM implementation needs approved credentials, representative examples, privacy rules and measured classification evaluation before making AI claims.

## Known deployment limitations

- This workspace had no Docker, PostgreSQL server or installed FastAPI/Temporal packages. The Compose stack and SDK imports were authored but not executed here.
- `temporalio/temporal` runs a persisted **development** server, not a production cluster. Pin verified image digests and a dependency lock after running the smoke suite in the intended environment.
- The one-time schema initializer is not a production migration history.
- Worker infrastructure failures retry independently from business failure budgets. Infrastructure retries are not reflected as provider business attempts if no provider response transaction committed.
- API health proves API/database readiness, not Temporal worker health. The smoke test proves end-to-end execution when actually run.
- Current Sites hosting uses a Worker-compatible runtime; this Python/PostgreSQL/Temporal stack was not silently replaced to fit it. No live public Site was deployed.
- Browser access to the local URL was blocked by the browser environment. Visual and interaction QA in a browser is outstanding. HTTP delivery and JS syntax were checked, which are not equivalent to browser QA.

## Reference documentation

- [Temporal Python SDK](https://python.temporal.io/)
- [Temporal exceptions](https://python.temporal.io/temporalio.exceptions.WorkflowAlreadyStartedError.html)
- [Temporal CLI](https://docs.temporal.io/cli)

These inform the SDK/development setup only; they do not substantiate any claim of completed deployment testing.
