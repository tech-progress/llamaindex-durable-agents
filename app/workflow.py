import re

from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent

from app.provider import make_proposal


CORPUS = [
    {"id": "policy:approval", "text": "Every invoice payment requires explicit human approval."},
    {"id": "policy:ledger", "text": "Approved payments are recorded once in the durable invoice ledger."},
    {"id": "policy:limits", "text": "This demo records amounts up to 100000 cents; it never transfers money."},
]


def retrieve(query):
    terms = set(re.findall(r"[a-z]+", query.lower()))
    ranked = sorted(
        CORPUS,
        key=lambda document: (
            -len(terms.intersection(re.findall(r"[a-z]+", document["text"].lower()))),
            document["id"],
        ),
    )
    return ranked[:2]


class PaymentRequest(StartEvent):
    request_id: str
    query: str
    amount_cents: int


class Retrieved(Event):
    request_id: str
    query: str
    amount_cents: int
    citations: list[dict[str, str]]


class Proposed(Event):
    request_id: str
    amount_cents: int
    proposal: str
    citations: list[dict[str, str]]


class ApprovalRequested(Event):
    request_id: str
    proposal: str
    citations: list[dict[str, str]]


class ApprovalDecision(Event):
    request_id: str
    approved: bool


class Authorized(Event):
    request_id: str
    amount_cents: int
    approved: bool
    citations: list[dict[str, str]]


class PaymentResult(StopEvent):
    request_id: str
    outcome: str
    citations: list[dict[str, str]]


class ApprovalWorkflow(Workflow):
    def __init__(self, pool, provider_settings, **kwargs):
        super().__init__(**kwargs)
        self.pool = pool
        self.provider_settings = provider_settings

    @step
    async def search(self, ctx: Context, ev: PaymentRequest) -> Retrieved:
        citations = retrieve(ev.query)
        await ctx.store.set("citations", citations)
        return Retrieved(
            request_id=ev.request_id, query=ev.query, amount_cents=ev.amount_cents, citations=citations
        )

    @step
    async def plan(self, ctx: Context, ev: Retrieved) -> Proposed:
        proposal = await make_proposal(
            ev.amount_cents, ev.query, ev.citations, self.provider_settings
        )
        await ctx.store.set("proposal", proposal)
        return Proposed(
            request_id=ev.request_id,
            amount_cents=ev.amount_cents,
            proposal=proposal,
            citations=ev.citations,
        )

    @step
    async def approve(self, ctx: Context, ev: Proposed) -> Authorized:
        decision = await ctx.wait_for_event(
            ApprovalDecision,
            waiter_id=f"approval:{ev.request_id}",
            requirements={"request_id": ev.request_id},
            waiter_event=ApprovalRequested(
                request_id=ev.request_id, proposal=ev.proposal, citations=ev.citations
            ),
            timeout=None,
        )
        recorded = await self.pool.fetchval(
            "SELECT approved FROM demo_approvals WHERE request_id = $1", ev.request_id
        )
        if recorded is None or recorded != decision.approved:
            raise ValueError("Approval does not match the durable decision")
        await ctx.store.set("approved", recorded)
        return Authorized(
            request_id=ev.request_id,
            amount_cents=ev.amount_cents,
            approved=recorded,
            citations=ev.citations,
        )

    @step
    async def record(self, ev: Authorized) -> PaymentResult:
        if ev.approved:
            async with self.pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO demo_ledger (request_id, amount_cents) VALUES ($1, $2) "
                        "ON CONFLICT (request_id) DO NOTHING",
                        ev.request_id,
                        ev.amount_cents,
                    )
                    amount = await connection.fetchval(
                        "SELECT amount_cents FROM demo_ledger WHERE request_id = $1",
                        ev.request_id,
                    )
                    if amount != ev.amount_cents:
                        raise ValueError("Conflicting ledger payload")
        return PaymentResult(
            request_id=ev.request_id,
            outcome="recorded" if ev.approved else "rejected",
            citations=ev.citations,
        )
