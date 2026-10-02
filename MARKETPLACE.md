# Deploy and Host LlamaIndex durable agents on Railway

Run an authenticated human-approval workflow using [LlamaIndex Workflows](https://github.com/run-llama/llama-agents) and [DBOS](https://github.com/dbos-inc/dbos-transact-py), with private PostgreSQL persistence. This is a single-operator evaluation recipe.

## About Hosting LlamaIndex durable agents

One Docker-based API searches sample policies, proposes a demo invoice ledger entry, waits for human approval, and records the authorized entry. DBOS persists the real LlamaIndex step runtime, run store and events. A single leased executor identity allows a stopped/crashed process to be replaced against the same database. PostgreSQL stores workflow history, decisions and SQL-idempotent ledger records on a volume.

## Why Deploy LlamaIndex durable agents

Explore durable human-in-the-loop orchestration without an external queue, GPU or mandatory provider account. Every API/debugger/docs route requires a generated bearer secret except minimal liveness/readiness. Only the API is public. Deterministic mode makes no provider calls; optional server-side OpenAI proposals incur provider charges.

## Common Use Cases

- Evaluate policy-grounded agent proposals with a real approval boundary.
- Learn how pending workflow runs recover after API process replacement.
- Adapt SQL-idempotent demo effects to a carefully reviewed business operation.

## Dependencies for LlamaIndex durable agents

Pinned Python 3.12 application, LlamaIndex Workflows/DBOS packages, and private PostgreSQL 17.9. No DBOS Conductor or paid model is required for the default sample.

### Deployment Dependencies

The `release-v1` GitHub source, a generated API token, generated database password and a PostgreSQL volume are required. Optional hosted proposals require `PROPOSAL_MODE=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL` and a bounded timeout; hosted model quality and availability are not qualification claims. Disable automatic GitHub deployments on an initialized API. Stop the old API deployment and confirm zero running instances before replacement; accept downtime while the lease is released or expires. Single replica only; no automatic rolling handover, HA, tenant isolation, payment transfer or production readiness claim.
