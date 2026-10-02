import unittest

from app.workflow import CORPUS, retrieve


class RetrievalTests(unittest.TestCase):
    def test_returns_grounded_invoice_citations(self):
        results = retrieve("invoice payment human approval")
        self.assertEqual(results[0]["id"], "policy:approval")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(document in CORPUS for document in results))

    def test_no_paid_provider_or_nondeterministic_order(self):
        self.assertEqual(retrieve("no matches xyz"), retrieve("no matches xyz"))
        self.assertEqual(retrieve(""), CORPUS[:2])
