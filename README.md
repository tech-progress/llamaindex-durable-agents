# LlamaIndex durable agents

An **evaluation template** combining [LlamaIndex Workflows](https://github.com/run-llama/llama-agents) and [DBOS Python](https://github.com/dbos-inc/dbos-transact-py). The current template release is `v1.0.3`. This is an approval-agent starter, not a payment processor or an autonomous finance product. Source releases and marketplace publication are separate: require the exact-source checks in `PUBLISHING.md`, not historical proof from another revision.

## What runs

- **LlamaIndex API:** one non-root Docker container, one Uvicorn worker, one leased executor slot. The native LlamaIndex workflow searches a baked-in policy corpus, proposes an invoice entry, suspends for human approval, then records an approved demo ledger entry.
- **Postgres:** private PostgreSQL 17.11 with a 5 GB `/var/lib/postgresql/data` volume, pinned to `postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652`. Holds DBOS execution state, LlamaIndex run store, context state, journal/ticks, event history, requests, immutable approval decisions and ledger rows. No public database port/proxy. No application volume.
- Optional hosted proposals use OpenAI's Responses API inside the actual LlamaIndex `plan` step; deterministic mode needs no provider and makes no paid calls.

Pinned runtime: `llama-index-workflows==2.25.0`, `llama-agents-dbos==0.7.0`, `llama-agents-server==0.8.0`, `dbos==2.31.1`; the complete Python dependency graph is in `uv.lock`. DBOS 3.2.0 was observed but rejected by the local compatibility gate: the LlamaIndex adapter still constructs queues using the DBOS 2 API. Python, uv and PostgreSQL images use immutable digests; Railway IaC is locked to `railway==3.6.0` in `bun.lock`.

## Railway configuration

`.railway/railway.ts` describes the graph. Application build is `Dockerfile`; start is `/app/start.sh`; routing port is 3000; health check is `/readyz` with a 120-second timeout. Generate independent API/database secrets, restore `template-defaults.json`, grant an HTTP domain only to **LlamaIndex API**, and attach the PostgreSQL volume. Use exactly one replica and stop the old API process before replacement; see the lease limitation below.

The distribution source is `tech-progress/llamaindex-durable-agents`, with `main` and `release-v1` branches, root `/`; IaC selects `release-v1`. Immutable `v1.0.3` identifies this release. Historical immutable `v1.0.1` identifies commit `989e904`; it and `v1.0.0` remain unchanged. Fork maintainers must change `TEMPLATE_SOURCE_REPO`, establish their own slash-free release branch, and authorize Railway's GitHub App. Watch patterns derive from the selected root. These are maintainer-local IaC inputs, not app runtime variables. IaC uses native secret functions, never deterministic SDK `randomString`; for a disposable source bootstrap supply cryptographically random `TEMPLATE_POSTGRES_PASSWORD` and `TEMPLATE_API_TOKEN`, and preserve initialized credentials when reapplying.

## Environment variables

| Variable | Required/default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required on API | Dedicated PostgreSQL URL; Railway references `Postgres` credentials and `RAILWAY_PRIVATE_DOMAIN`. Scheme must be `postgresql://`; do not expose/log it. |
| `API_TOKEN` | Required, generated 48 characters | Bearer secret; minimum 32 characters. Protects **all** run/event/store, engine/debugger, docs and unknown routes; only exact GET `/healthz` and `/readyz` are public. |
| `PORT` | API 3000; database 5432 | Railway listener/routing port; app start binds `0.0.0.0`. |
| `DBOS_EXECUTOR_PREFIX` | `llamaindex-approval` | Permanent lease identity. Slot `llamaindex-approval-0` survives process/container replacement. Do not use ephemeral deployment IDs. |
| `PROPOSAL_MODE` | `deterministic` | `openai` enables the optional hosted proposal path. |
| `OPENAI_API_KEY` | Required only in `openai` mode | Server-side provider credential supplied separately; deliberately absent from generated template defaults. Never send it in a request or commit it. |
| `OPENAI_MODEL` | `gpt-4.1-mini-2025-04-14` | Hosted proposal model; unused offline. Model access depends on your account. |
| `OPENAI_TIMEOUT_SECONDS` | 30, range 1–120 | Bounded hosted HTTP timeout; errors do not bypass approval. |
| `POSTGRES_USER` | `workflows` on database | Dedicated DBOS/LlamaIndex migration owner. |
| `POSTGRES_DB` | `workflows` on database | Dedicated persistent database. |
| `POSTGRES_PASSWORD` | Required, generated 32 characters | Database secret; Compose requires a locally exported value. Changing it alone does not rotate an existing PostgreSQL user's password. |
| `PGDATA` | `/var/lib/postgresql/data/pgdata` | PostgreSQL persistent data path. |

`.env.example` contains placeholders, not usable secrets. For Compose, export hex secrets so the password is URL-safe. DBOS admin server is explicitly disabled. `OPENAI_API_KEY` is not required or read by deterministic proposals. No DBOS cloud/Conductor account is needed.

## Local verification and use

From this directory, install `uv`, Bun, Docker Compose, `jq`, `rg`, OpenSSL and GNU `timeout`:

```bash
./scripts/verify.sh --static
./scripts/verify.sh --local
```

The local verifier builds without cache, starts an empty isolated `rt-llama-cb5c13c4` project, exposes **only** loopback API ports (18211 and temporary contender port 18213), runs container tests and SQL replay tests, asserts the actual PostgreSQL 17.11 server with private default settings, kills/replaces API containers while approval is pending, checks original run IDs and event history, verifies outbox recovery and conflict rejection, records CPU/memory, and removes its own containers/network/volumes on exit. It refuses pre-existing resources with that project label. Hosted-provider HTTP is mocked; no paid calls are made. Integration tests are explicitly skipped in the host-only suite and run against the isolated database in `--local`.

For manual use (do not run concurrently with the verifier; it reserves this same project):

```bash
export API_TOKEN="$(openssl rand -hex 24)"
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
docker compose -p rt-llama-cb5c13c4 up --build -d --wait --wait-timeout 120
export REQUEST_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"
curl --fail http://127.0.0.1:18211/runs -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d "{\"request_id\":\"$REQUEST_ID\",\"query\":\"invoice payment human approval\",\"amount_cents\":2500}"
curl --fail "http://127.0.0.1:18211/runs/$REQUEST_ID/events" -H "Authorization: Bearer $API_TOKEN"
curl --fail "http://127.0.0.1:18211/runs/$REQUEST_ID/approval" -H "Authorization: Bearer $API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"approved":true}'
curl --fail "http://127.0.0.1:18211/runs/$REQUEST_ID" -H "Authorization: Bearer $API_TOKEN"
docker compose -p rt-llama-cb5c13c4 down --volumes
```

Deleting the volume is appropriate only for disposable demo data. Railway users should back up their database instead. The sample never moves real money.

## API and safety contract

- `POST /runs` requires a UUID `request_id`, bounded `query`, and integer `amount_cents` from 1 to 100000. Exact repeated payloads return the same persisted handler/run; reuse with a different payload returns 409.
- `GET /runs/{id}` and `/runs/{id}/events` read persisted run metadata, result and event history. One API secret grants full access to all runs; this is **not** tenant isolation or role-based approval control.
- `POST /runs/{id}/approval` commits an immutable boolean approval before acknowledging. Same decisions can be retried; conflicting decisions return 409. A database-backed reconciler retries delivery to the original handler after restart. Duplicate messages do not create duplicate ledger effects.
- Native read-only server routes and debugger HTML are under `/engine/`, behind the same outer ASGI authentication. All native mutation routes return 405 even with authentication, so clients cannot forge events, bypass request reservations, cancel/purge runs or upload contexts. Upstream debugger HTML loads versioned JavaScript/CSS from jsDelivr; browser/CDN behavior is unverified. Use the authenticated JSON APIs for diagnostics, not the debugger as an approval UI. `/docs`, `/redoc` and `/openapi.json` also require bearer authentication; browser sessions do not automatically carry it. Never put tokens in a URL.
- SQL `PRIMARY KEY (request_id)` and one transaction make the **demo ledger write** idempotent even if DBOS replays an interrupted step. This is not a general exactly-once external API guarantee.

## Durability and boundaries

The integration uses documented `DBOSRuntime.create_workflow_store()` and `build_server_runtime()`, passed to `WorkflowServer`. Actual `Workflow`/`@step`/`Context.store`/`Context.wait_for_event` operations run on the DBOS adapter; native run IDs, event history, ticks, context state and approval waits persist in PostgreSQL. It is not an in-memory server wrapped in a DBOS function.

The upstream executor lease is **experimental**: one slot, a 2-second heartbeat, 10-second crash expiry and bounded 45-second acquisition. The initial DBOS configuration explicitly sets `executor_id` to `${DBOS_EXECUTOR_PREFIX}-0`, matching that single leased slot; DBOS 2 ignores a second constructor's attempted identity change. Startup asserts the identity and active lease. A dead process releases identity by lease expiry; a graceful stop releases it. A replacement must run the same workflow name `invoice-approval-v1`, DBOS application version `approval-v1` and executor prefix against the same database. Do not cancel pending workflows during shutdown.

**Replacement requires single-replica downtime.** Zero overlap is configured, but it does not mean a readiness-gated replacement can acquire a slot held by the predecessor. Disable automatic GitHub deployments for an initialized API service. Explicitly stop/drain the old API deployment, confirm it has no running instances, then redeploy the same release channel and wait for `/readyz`. Local contender tests prove the replacement stays unready while the old slot is held, then resumes the original pending approval after explicit stop. This is not zero-downtime rolling handover. Do not scale to two replicas, change the executor prefix, or claim high availability.

Hosted mode sends the query and policy excerpts to OpenAI and incurs model charges. Successful proposal-step outputs are journaled; a crash after the provider receives a request but before step persistence can **repeat the paid call**. No billing exactly-once guarantee, provider availability SLA, output quality gate or paid-provider smoke is claimed. Keep model output advisory; approval and ledger amount come from validated server data, never model-generated tool arguments.

See `SUPPORT.md` and `UPGRADE.md` for operational boundaries. `LICENSE` grants MIT only for recipe-owned code; upstream LlamaIndex/DBOS, PostgreSQL, LGPL Psycopg and other dependencies retain their own notices and licenses. `THIRD_PARTY_NOTICES.md` describes the source-build distribution boundary, replacement/source rights and the exact runtime inventory. The final image excludes uv/uvx and the bundled Psycopg binary wheel; it retains Python/package/Debian notices and dynamically loads Debian libpq. No model weights or frontend bundle are redistributed by this recipe.
