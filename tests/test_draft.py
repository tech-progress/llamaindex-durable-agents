import copy
import json
import subprocess
import unittest
from pathlib import Path

from scripts.draft import audit, restore


ROOT = Path(__file__).resolve().parents[1]


class DraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(subprocess.check_output(
            [str(ROOT / "node_modules/.bin/railway-iac-ts"), ".railway/railway.ts"], cwd=ROOT
        ))

    def contaminated(self):
        return {"data": {"template": {"name": "Unrelated seed", "serializedConfig": {
            "services": {name: {
                "name": name,
                "source": {"image": "wrong:latest", "repo": "wrong/repo", "branch": "bad", "rootDirectory": "/bad"},
                "build": {"builder": "RAILPACK", "buildCommand": "wrong"},
                "deploy": {"startCommand": "wrong", "cronSchedule": "* * * * *", "numReplicas": 3},
                "networking": {"serviceDomains": {"wrong": {"port": 9999}}, "tcpProxies": {"public": {"port": 5432}}, "customDomains": {"wrong": {}}},
                "volumeMounts": {"existing-volume": {"mountPath": "/bad", "sizeMB": 1}},
                "variables": {"API_TOKEN": {"defaultValue": "bad", "isOptional": True}, "UNEXPECTED": {"defaultValue": "wrong"}},
            } for name in ("LlamaIndex API", "Postgres")}
        }}}}

    def test_contaminated_fixture_restored_and_negative_audit(self):
        draft = self.contaminated()
        with self.assertRaises(ValueError):
            audit(draft, self.graph)
        clean = restore(draft, self.graph)
        audit(clean, self.graph)
        services = clean["data"]["template"]["serializedConfig"]["services"]
        self.assertNotIn("image", services["LlamaIndex API"]["source"])
        self.assertEqual(list(services["Postgres"]["source"]), ["image"])
        self.assertEqual(services["Postgres"]["networking"]["serviceDomains"], {})
        self.assertEqual(services["Postgres"]["volumeMounts"]["existing-volume"]["mountPath"], "/var/lib/postgresql/data")
        self.assertEqual(services["LlamaIndex API"]["volumeMounts"], {})
        self.assertNotIn("cronSchedule", services["LlamaIndex API"]["deploy"])
        self.assertEqual(clean, restore(clean, self.graph))

    def test_each_contract_mutation_is_rejected(self):
        clean = restore(self.contaminated(), self.graph)
        for name in ("LlamaIndex API", "Postgres"):
            for field in ("source", "build", "deploy", "networking", "volumeMounts", "variables"):
                damaged = copy.deepcopy(clean)
                damaged["data"]["template"]["serializedConfig"]["services"][name][field]["unexpected"] = "bad"
                with self.assertRaises(ValueError, msg=f"{name}.{field}"):
                    audit(damaged, self.graph)

    def test_unexpected_services_and_missing_database_volume_fail_closed(self):
        draft = self.contaminated()
        del draft["data"]["template"]["serializedConfig"]["services"]["Postgres"]
        with self.assertRaises(ValueError):
            restore(draft, self.graph)
        draft = self.contaminated()
        draft["data"]["template"]["serializedConfig"]["services"]["Postgres"]["volumeMounts"] = {}
        with self.assertRaises(ValueError):
            restore(draft, self.graph)
