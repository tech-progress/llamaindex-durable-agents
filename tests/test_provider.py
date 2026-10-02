import json
import unittest
from unittest.mock import patch

import httpx

from app.provider import ProviderSettings, make_proposal


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_deterministic_never_calls_transport(self):
        def forbidden(request):
            raise AssertionError("Offline mode must not call a provider")
        text = await make_proposal(100, "invoice", [], ProviderSettings(), httpx.MockTransport(forbidden))
        self.assertIn("100 cents", text)

    async def test_responses_contract_with_mock_not_paid_call(self):
        def mock(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/responses")
            self.assertEqual(request.headers["Authorization"], "Bearer test-only")
            data = json.loads(request.content)
            self.assertFalse(data["store"])
            self.assertEqual(data["max_output_tokens"], 256)
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "Approve a demo entry under policy:approval."}]}
            ]})
        text = await make_proposal(100, "invoice", [], ProviderSettings(mode="openai", api_key="test-only"), httpx.MockTransport(mock))
        self.assertIn("policy:approval", text)

    async def test_provider_error_is_redacted(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(401, text="secret-token-in-body"))
        with self.assertRaisesRegex(RuntimeError, "Hosted proposal failed") as error:
            await make_proposal(100, "invoice", [], ProviderSettings(mode="openai", api_key="test-only"), transport)
        self.assertNotIn("secret", str(error.exception))

    def test_configuration_fails_closed(self):
        for variables in ({"PROPOSAL_MODE": "other"}, {"PROPOSAL_MODE": "openai"}, {"OPENAI_TIMEOUT_SECONDS": "nan"}, {"OPENAI_TIMEOUT_SECONDS": "121"}):
            with patch.dict("os.environ", variables, clear=True):
                with self.assertRaises(ValueError):
                    ProviderSettings.from_env()
