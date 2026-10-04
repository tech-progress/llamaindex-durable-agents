import copy
import json
import subprocess
import tomllib
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

    def test_postgres_pin_and_recipe_version(self):
        postgres_image = "postgres:17.11-bookworm@sha256:639ab7ceb90e13123085b741fb31ef493fba25463002f6da665352e7b534b652"
        resources = {resource["name"]: resource for resource in self.graph["graph"]["resources"]}
        self.assertEqual(resources["Postgres"]["source"], {"type": "image", "image": postgres_image})
        compose = ROOT.joinpath("compose.yaml").read_text()
        self.assertIn(f"    image: {postgres_image}\n", compose)
        version = ROOT.joinpath("VERSION").read_text().strip()
        self.assertEqual(version, "1.0.3")
        self.assertEqual(tomllib.loads(ROOT.joinpath("pyproject.toml").read_text())["project"]["version"], version)
        locked_recipe = next(package for package in tomllib.loads(ROOT.joinpath("uv.lock").read_text())["package"]
                             if package["name"] == "railway-llamaindex-durable-agents")
        self.assertEqual(locked_recipe["version"], version)
        self.assertIn(f"    image: rt-llama-cb5c13c4-api:{version}\n", compose)
        postgres_version = postgres_image.split(":", 1)[1].split("-", 1)[0]
        self.assertIn(f"private PostgreSQL {postgres_version}.", ROOT.joinpath("MARKETPLACE.md").read_text())

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
