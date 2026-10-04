import concurrent.futures
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18211"
TOKEN = os.environ["API_TOKEN"]


def compose(*arguments):
    return subprocess.run(
        ["docker", "compose", "-p", "rt-llama-cb5c13c4", "-f", str(ROOT / "compose.yaml"), *arguments],
        text=True, capture_output=True, check=True, timeout=120,
    ).stdout


def request(path, method="GET", payload=None, auth=True, expected=200, base=BASE):
    headers = {"Content-Type": "application/json"}
    if auth:
        headers["Authorization"] = f"Bearer {TOKEN if auth is True else auth}"
    data = json.dumps(payload).encode() if payload is not None else None
    message = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        response = urllib.request.urlopen(message, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    assert response.status == expected, f"{method} {path}: unexpected HTTP {response.status}"
    content = response.read().decode()
    return json.loads(content) if response.headers.get("content-type", "").startswith("application/json") else content


def wait(predicate, label, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.3)
    raise AssertionError(f"Timed out waiting for {label}")


def waiting_for_approval(request_id):
    events = request(f"/runs/{request_id}/events")["events"]
    return events if any(event["event"]["type"] == "ApprovalRequested" for event in events) else None


def create():
    request_id = str(uuid4())
    payload = {"request_id": request_id, "query": "invoice payment human approval", "amount_cents": 2500}
    run = request("/runs", "POST", payload, expected=202)
    wait(lambda: waiting_for_approval(request_id), "persisted approval event")
    assert run["run_id"] and run["ledger_entries"] == 0
    return payload, run


def replace_process():
    compose("kill", "-s", "SIGKILL", "api")
    compose("rm", "-f", "api")
    compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "api")
    assert request("/readyz", auth=False) == {"ok": True}


def completed(request_id):
    result = request(f"/runs/{request_id}")
    assert result["status"] != "failed", "Workflow failed"
    return result if result["status"] == "completed" else None


def handover():
    contender_base = "http://127.0.0.1:18213"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 18213))
    payload, original = create()
    request_id = payload["request_id"]
    initial_events = request(f"/runs/{request_id}/events")["events"]
    query = "SELECT holder FROM dbos.executor_leases WHERE slot_id='llamaindex-approval-0'"
    owner = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c", query).strip()
    contender_name = f"rt-llama-cb5c13c4-handover-{uuid4().hex}"
    contender = compose("run", "--detach", "--no-deps", "--publish", "127.0.0.1:18213:3000", "--name", contender_name, "api").strip()
    try:
        time.sleep(8)
        try:
            request("/readyz", auth=False, base=contender_base)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        else:
            raise AssertionError("A contender cannot become ready while the original single-slot owner is running")
        held = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c", query).strip()
        assert held == owner and owner, "Overlapping processes must not steal the leased executor identity"
        assert request(f"/runs/{request_id}")["ledger_entries"] == 0
        compose("stop", "--timeout", "15", "api")

        def ready():
            try:
                return request("/readyz", auth=False, base=contender_base) == {"ok": True}
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                return False

        wait(ready, "contender acquisition after explicit predecessor stop", seconds=35)
        acquired = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c", query).strip()
        assert acquired and acquired != owner, "Replacement must acquire a new holder for the same stable slot"
        recovered = request(f"/runs/{request_id}", base=contender_base)
        assert recovered["run_id"] == original["run_id"]
        events = request(f"/runs/{request_id}/events", base=contender_base)["events"]
        assert events[:len(initial_events)] == initial_events
        request(f"/runs/{request_id}/approval", "POST", {"approved": True}, expected=202, base=contender_base)

        def recorded():
            result = request(f"/runs/{request_id}", base=contender_base)
            assert result["status"] != "failed"
            return result if result["status"] == "completed" else None

        result = wait(recorded, "original pending approval after exclusive handover")
        assert result["ledger_entries"] == 1 and result["result"]["outcome"] == "recorded"
        print("PASS: overlap contender stays unready and cannot steal lease; explicit stop permits exclusive handover with original approval/event history and one ledger effect")
    finally:
        subprocess.run(["docker", "rm", "--force", contender], check=True, capture_output=True, timeout=30)
        compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "api")


def main():
    assert os.environ.get("PROPOSAL_MODE", "deterministic") == "deterministic"
    for path in ("/healthz", "/readyz"):
        assert request(path, auth=False) == {"ok": True}
    paths = ("/", "/runs", "/docs", "/redoc", "/openapi.json", "/engine/", "/engine/workflows", "/engine/handlers", "/engine/events/missing", "/engine/results/missing", "/engine/health", "/store")
    for path in paths:
        request(path, auth=False, expected=401)
        request(path, auth="incorrect-token", expected=401)
    request("/runs", "POST", {}, auth=False, expected=401)
    assert "openapi" in request("/openapi.json")
    request("/engine/workflows")
    request("/engine/handlers")
    assert isinstance(request("/engine/"), str)
    for path in ("/engine/workflows/invoice-approval-v1/run", "/engine/events/missing", "/engine/handlers/missing/cancel"):
        request(path, "POST", {}, expected=405)

    payload, original = create()
    request_id = payload["request_id"]
    initial_events = request(f"/runs/{request_id}/events")["events"]
    replace_process()
    recovered = request(f"/runs/{request_id}")
    assert recovered["run_id"] == original["run_id"], "Replacement must resume the ORIGINAL run"
    recovered_events = request(f"/runs/{request_id}/events")["events"]
    assert recovered_events[:len(initial_events)] == initial_events, "Event history must persist"
    request(f"/engine/handlers/{request_id}", expected=202)
    request(f"/runs/{request_id}/approval", "POST", {"approved": True}, expected=202)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda ignored: request("/runs", "POST", payload, expected=202), range(4)))
    assert all(response["run_id"] == original["run_id"] for response in responses)
    request("/runs", "POST", {**payload, "amount_cents": 2501}, expected=409)
    request(f"/runs/{request_id}/approval", "POST", {"approved": False}, expected=409)
    request(f"/runs/{request_id}/approval", "POST", {"approved": True}, expected=202)
    done = wait(lambda: completed(request_id), "approved original run completion")
    assert done["ledger_entries"] == 1 and done["result"]["outcome"] == "recorded"
    assert done["result"]["citations"][0]["id"] == "policy:approval"
    replace_process()
    assert request(f"/runs/{request_id}")["run_id"] == original["run_id"]
    assert request(f"/runs/{request_id}")["ledger_entries"] == 1

    denied, denied_run = create()
    request(f"/runs/{denied['request_id']}/approval", "POST", {"approved": False}, expected=202)
    rejected = wait(lambda: completed(denied["request_id"]), "rejected run completion")
    assert rejected["ledger_entries"] == 0 and rejected["result"]["outcome"] == "rejected"

    pending, pending_run = create()
    compose("kill", "-s", "SIGKILL", "api")
    compose("rm", "-f", "api")
    compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-v", "ON_ERROR_STOP=1", "-c",
            f"INSERT INTO demo_approvals (request_id, approved) VALUES ('{pending['request_id']}', true)")
    compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "api")
    delivered = wait(lambda: completed(pending["request_id"]), "persisted outbox delivery after process replacement")
    assert delivered["run_id"] == pending_run["run_id"] and delivered["ledger_entries"] == 1
    count = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c", "SELECT count(*) FROM demo_ledger")
    assert count.strip() == "2", "Exactly one SQL ledger effect per approved request"
    identities = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c",
                         "SELECT count(*) FROM dbos.workflow_status WHERE executor_id <> 'llamaindex-approval-0'")
    assert identities.strip() == "0", "DBOS must persist the stable leased executor identity, not local or an ephemeral deployment ID"
    lease = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c",
                    "SELECT count(*) FROM dbos.executor_leases WHERE slot_id='llamaindex-approval-0' AND holder IS NOT NULL")
    assert lease.strip() == "1", "Exactly one stable executor slot must be held"
    postgres_id = compose("ps", "-q", "postgres").strip()
    api_id = compose("ps", "-q", "api").strip()
    ports = json.loads(subprocess.check_output(
        ["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", postgres_id], text=True, timeout=15
    ))
    assert not ports, "PostgreSQL must have no public host binding"
    postgres_version = compose("exec", "-T", "postgres", "postgres", "--version").strip()
    client_version = compose("exec", "-T", "postgres", "psql", "--version").strip()
    defaults = json.loads(compose(
        "exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c",
        "SELECT json_build_object('version', version(), 'version_num', current_setting('server_version_num'), "
        "'ssl', current_setting('ssl'), 'password_encryption', current_setting('password_encryption'), "
        "'database', current_database(), 'owner', current_user, "
        "'login_roles', (SELECT count(*) FROM pg_roles WHERE rolcanlogin), "
        "'owner_superuser', (SELECT rolsuper FROM pg_roles WHERE rolname=current_user))",
    ))
    assert postgres_version.startswith("postgres (PostgreSQL) 17.11 "), postgres_version
    assert client_version.startswith("psql (PostgreSQL) 17.11 "), client_version
    assert defaults["version_num"] == "170011" and defaults["version"].startswith("PostgreSQL 17.11 "), defaults
    assert defaults["ssl"] == "off" and defaults["password_encryption"] == "scram-sha-256", defaults
    assert defaults["database"] == "workflows" and defaults["owner"] == "workflows", defaults
    assert defaults["login_roles"] == 1 and defaults["owner_superuser"] is True, defaults
    print(f"PASS: actual PostgreSQL binary {postgres_version}; client {client_version}; private defaults {json.dumps(defaults, sort_keys=True)}")
    bindings = json.loads(subprocess.check_output(
        ["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", api_id], text=True, timeout=15
    ))
    assert bindings == {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18211"}]}
    handover()
    count = compose("exec", "-T", "postgres", "psql", "-U", "workflows", "-d", "workflows", "-At", "-c", "SELECT count(*) FROM demo_ledger")
    assert count.strip() == "3", "Handover adds exactly one approved ledger effect"
    print("PASS: full auth boundary; persisted events; original-run crash recovery; immutable approvals; concurrent ID retries; durable outbox; rejected-run safety; exactly three ledger rows for three approved requests including handover")


if __name__ == "__main__":
    main()
