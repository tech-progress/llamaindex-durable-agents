import os
import unittest
from uuid import uuid4

import asyncpg

from app.provider import ProviderSettings
from app.workflow import ApprovalWorkflow, Authorized


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "Requires isolated verification PostgreSQL")
class LedgerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_replayed_sql_effect_is_once_and_conflicting_payload_rejected(self):
        pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2)
        request_id = str(uuid4())
        try:
            await pool.execute(
                "INSERT INTO demo_requests (request_id, query, amount_cents) VALUES ($1, 'replay-test', 99)", request_id
            )
            workflow = ApprovalWorkflow(pool, ProviderSettings())
            event = Authorized(request_id=request_id, amount_cents=99, approved=True, citations=[])
            await workflow.record(event)
            await workflow.record(event)
            self.assertEqual(await pool.fetchval("SELECT count(*) FROM demo_ledger WHERE request_id=$1", request_id), 1)
            with self.assertRaisesRegex(ValueError, "Conflicting ledger payload"):
                await workflow.record(Authorized(request_id=request_id, amount_cents=100, approved=True, citations=[]))
            self.assertEqual(await pool.fetchval("SELECT amount_cents FROM demo_ledger WHERE request_id=$1", request_id), 99)
        finally:
            await pool.execute("DELETE FROM demo_ledger WHERE request_id=$1", request_id)
            await pool.execute("DELETE FROM demo_requests WHERE request_id=$1", request_id)
            await pool.close()
