import unittest

import httpx
from starlette.responses import JSONResponse

from app.security import AuthBoundary


TOKEN = "test-only-token-" + "x" * 40


async def endpoint(scope, receive, send):
    await JSONResponse({"ok": True})(scope, receive, send)


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_sensitive_paths_require_auth(self):
        transport = httpx.ASGITransport(app=AuthBoundary(endpoint, TOKEN))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/", "/runs", "/docs", "/redoc", "/openapi.json", "/engine/", "/engine/workflows", "/engine/events/demo", "/engine/handlers", "/engine/results/demo", "/engine/health", "/store", "/healthz/"):
                self.assertEqual((await client.get(path)).status_code, 401, path)
                self.assertEqual((await client.get(path, headers={"Authorization": "Bearer wrong"})).status_code, 401, path)
                self.assertEqual((await client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})).status_code, 200, path)
            for path in ("/healthz", "/readyz"):
                self.assertEqual((await client.get(path)).json(), {"ok": True})
                self.assertEqual((await client.post(path)).status_code, 401)

    async def test_authenticated_raw_mutations_are_disabled(self):
        transport = httpx.ASGITransport(app=AuthBoundary(endpoint, TOKEN))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/engine/workflows/invoice-approval-v1/run", "/engine/events/demo", "/engine/handlers/demo/cancel"):
                response = await client.post(path, headers={"Authorization": f"Bearer {TOKEN}"})
                self.assertEqual(response.status_code, 405)
