import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import asyncpg
import httpx
from dbos import DBOS
from fastapi import FastAPI, HTTPException
from llama_agents.dbos import DBOSRuntime
from llama_agents.server import HandlerQuery, WorkflowServer
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from app.security import AuthBoundary
from app.provider import ProviderSettings
from app.workflow import ApprovalDecision, ApprovalWorkflow


SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_requests (
    request_id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS demo_approvals (
    request_id TEXT PRIMARY KEY REFERENCES demo_requests(request_id),
    approved BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS demo_ledger (
    request_id TEXT PRIMARY KEY REFERENCES demo_requests(request_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents BETWEEN 1 AND 100000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    query: str = Field(min_length=1, max_length=256)
    amount_cents: int = Field(ge=1, le=100000, strict=True)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool = Field(strict=True)


async def engine_error(request, exception):
    return JSONResponse({"detail": "Workflow operation failed"}, status_code=500)


@asynccontextmanager
async def lifespan(api):
    database_url = os.environ["DATABASE_URL"]
    provider_settings = ProviderSettings.from_env()
    executor_prefix = os.environ.get("DBOS_EXECUTOR_PREFIX", "llamaindex-approval")
    api.state.ready = False
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5, command_timeout=15)
    await pool.execute(SCHEMA)
    DBOS(config={
        "name": "llamaindex-durable-agents",
        "system_database_url": database_url,
        "application_version": "approval-v1",
        "executor_id": f"{executor_prefix}-0",
        "run_admin_server": False,
        "sys_db_pool_size": 5,
    })
    runtime = DBOSRuntime(
        pool_size=5,
        pool_min_size=1,
        max_recovery_attempts=20,
        _experimental_executor_lease={
            "pool_size": 1,
            "slot_prefix": executor_prefix,
            "heartbeat_interval": 2.0,
            "lease_timeout": 10.0,
            "acquire_timeout": 45.0,
        },
    )
    store = runtime.create_workflow_store()
    server = WorkflowServer(
        workflow_store=store,
        runtime=runtime.build_server_runtime(idle_timeout=86400),
        exception_handlers={Exception: engine_error},
        accept_context_api=False,
        middleware=[],
    )
    server.add_workflow(
        "invoice-approval-v1",
        ApprovalWorkflow(pool, provider_settings, runtime=runtime, workflow_name="invoice-approval-v1", timeout=None),
        additional_events=[ApprovalDecision],
    )
    api.state.pool = pool
    api.state.store = store
    api.state.runtime = runtime
    api.state.lock = asyncio.Lock()
    api.state.engine = server.app
    await server.start()
    if DBOS.executor_id != f"{executor_prefix}-0" or runtime.lease_lost_event is None:
        raise RuntimeError("Stable executor identity and exclusive lease must be active")
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
        api.state.client = client
        task = asyncio.create_task(reconcile(api))
        api.state.ready = True
        try:
            yield
        finally:
            api.state.ready = False
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await server.stop()
            await pool.close()


async def ensure_started(api, record):
    request_id = record["request_id"]
    handlers = await api.state.store.query(HandlerQuery(handler_id_in=[request_id]))
    if handlers:
        return
    response = await api.state.client.post(
        "/workflows/invoice-approval-v1/run-nowait",
        json={"handler_id": request_id, "kwargs": {
            "request_id": request_id,
            "query": record["query"],
            "amount_cents": record["amount_cents"],
        }},
    )
    if response.status_code != 200:
        raise RuntimeError("Could not persist workflow handler")


async def reconcile(api):
    while True:
        try:
            async with api.state.lock:
                records = await api.state.pool.fetch("SELECT * FROM demo_requests ORDER BY created_at")
                for record in records:
                    await ensure_started(api, record)
                approvals = await api.state.pool.fetch("SELECT * FROM demo_approvals")
                for approval in approvals:
                    request_id = approval["request_id"]
                    handlers = await api.state.store.query(HandlerQuery(handler_id_in=[request_id]))
                    if handlers and handlers[0].status == "running":
                        response = await api.state.client.post(
                            f"/events/{request_id}",
                            json={"event": {"type": "ApprovalDecision", "value": {
                                "request_id": request_id, "approved": approval["approved"],
                            }}},
                        )
                        if response.status_code not in (200, 409):
                            raise RuntimeError("Approval delivery failed")
        except Exception:
            logging.exception("Durable request/approval reconciliation will retry")
        await asyncio.sleep(1)


api = FastAPI(title="Durable invoice approval", version="1.0.0", lifespan=lifespan)


@api.get("/healthz", include_in_schema=False)
async def health():
    return {"ok": True}


@api.get("/readyz", include_in_schema=False)
async def ready():
    try:
        runtime = api.state.runtime
        lease_lost = runtime.lease_lost_event
        if not api.state.ready or not runtime.is_launched or (lease_lost and lease_lost.is_set()):
            raise RuntimeError("Not ready")
        await api.state.pool.fetchval("SELECT 1")
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


@api.post("/runs", status_code=202)
async def start_run(payload: RunRequest):
    request_id = str(payload.request_id)
    async with api.state.lock:
        async with api.state.pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO demo_requests (request_id, query, amount_cents) VALUES ($1, $2, $3) "
                    "ON CONFLICT (request_id) DO NOTHING",
                    request_id, payload.query, payload.amount_cents,
                )
                record = await connection.fetchrow(
                    "SELECT * FROM demo_requests WHERE request_id = $1 FOR UPDATE", request_id
                )
                if record["query"] != payload.query or record["amount_cents"] != payload.amount_cents:
                    raise HTTPException(409, "Request ID already has a different payload")
        await ensure_started(api, record)
    return await get_run(payload.request_id)


@api.get("/runs/{request_id}")
async def get_run(request_id: UUID):
    key = str(request_id)
    if not await api.state.pool.fetchval("SELECT 1 FROM demo_requests WHERE request_id = $1", key):
        raise HTTPException(404, "Unknown request")
    handlers = await api.state.store.query(HandlerQuery(handler_id_in=[key]))
    handler = handlers[0] if handlers else None
    decision = await api.state.pool.fetchval("SELECT approved FROM demo_approvals WHERE request_id = $1", key)
    ledger = await api.state.pool.fetchrow("SELECT amount_cents FROM demo_ledger WHERE request_id = $1", key)
    return {
        "request_id": key,
        "run_id": handler.run_id if handler else None,
        "status": handler.status if handler else "reserved",
        "approved": decision,
        "ledger_entries": 1 if ledger else 0,
        "result": handler.result.model_dump() if handler and handler.result else None,
    }


@api.get("/runs/{request_id}/events")
async def get_events(request_id: UUID):
    await get_run(request_id)
    handlers = await api.state.store.query(HandlerQuery(handler_id_in=[str(request_id)]))
    if not handlers or not handlers[0].run_id:
        return {"events": []}
    events = await api.state.store.query_events(handlers[0].run_id)
    return {"events": [event.model_dump(mode="json") for event in events]}


@api.post("/runs/{request_id}/approval", status_code=202)
async def approve_run(request_id: UUID, payload: Decision):
    key = str(request_id)
    async with api.state.lock:
        async with api.state.pool.acquire() as connection:
            async with connection.transaction():
                if not await connection.fetchval("SELECT 1 FROM demo_requests WHERE request_id = $1", key):
                    raise HTTPException(404, "Unknown request")
                await connection.execute(
                    "INSERT INTO demo_approvals (request_id, approved) VALUES ($1, $2) "
                    "ON CONFLICT (request_id) DO NOTHING", key, payload.approved,
                )
                recorded = await connection.fetchval(
                    "SELECT approved FROM demo_approvals WHERE request_id = $1 FOR UPDATE", key
                )
                if recorded != payload.approved:
                    raise HTTPException(409, "Approval decision is immutable")
    return {"request_id": key, "approved": recorded}


async def engine(scope, receive, send):
    await api.state.engine(scope, receive, send)


api.mount("/engine", engine)
token = os.environ.get("API_TOKEN", "")
if len(token) < 32 or token.strip() != token:
    raise RuntimeError("API_TOKEN must contain at least 32 characters without surrounding whitespace")
app = AuthBoundary(api, token)
