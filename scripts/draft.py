import argparse
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NAME = "LlamaIndex durable agents"


def read(path):
    return json.loads(Path(path).read_text())


def config_of(draft):
    return draft.get("data", {}).get("template", draft).get("serializedConfig", draft)


def service_items(config):
    services = config["services"]
    return list(services.items()) if isinstance(services, dict) else list(enumerate(services))


def desired_services(graph):
    return {resource["name"]: resource for resource in graph["graph"]["resources"] if resource["type"] == "service"}


def canonical_service(existing, desired, defaults, descriptions, networking, volumes):
    result = copy.deepcopy(existing)
    name = existing["name"]
    result["source"] = {key: value for key, value in desired["source"].items() if key != "type"}
    result["build"] = copy.deepcopy(desired.get("build", {}))
    result["deploy"] = copy.deepcopy(desired.get("deploy", {}))
    result["variables"] = {
        key: {"defaultValue": value, "description": descriptions[name][key], "isOptional": False}
        for key, value in defaults[name].items()
    }
    port = networking[name]["publicPort"]
    result["networking"] = {
        "serviceDomains": {"<hasDomain>": {"port": port}} if port is not None else {},
        "tcpProxies": {},
        "customDomains": {},
    }
    volume = volumes.get(name)
    if volume:
        mounts = existing.get("volumeMounts", {})
        if len(mounts) != 1:
            raise ValueError("Database draft must already contain exactly one volume")
        key = next(iter(mounts))
        result["volumeMounts"] = {key: {"mountPath": volume["mountPath"], "sizeMB": volume["sizeMB"]}}
    else:
        result["volumeMounts"] = {}
    return result


def restore(draft, graph):
    output = copy.deepcopy(draft)
    config = config_of(output)
    desired = desired_services(graph)
    items = service_items(config)
    if sorted(service["name"] for _, service in items) != sorted(desired):
        raise ValueError("Draft service names differ from the exact expected set")
    defaults = read(ROOT / "template-defaults.json")
    descriptions = read(ROOT / "template-descriptions.json")
    networking = read(ROOT / "template-networking.json")
    volumes = read(ROOT / "template-volumes.json")
    for key, service in items:
        config["services"][key] = canonical_service(
            service, desired[service["name"]], defaults, descriptions, networking, volumes
        )
    if "data" in output:
        output["data"]["template"]["name"] = NAME
    elif "serializedConfig" in output:
        output["name"] = NAME
    return output


def audit(draft, graph):
    config = config_of(draft)
    expected = config_of(restore(draft, graph))
    template = draft.get("data", {}).get("template", draft)
    if "name" in template and template["name"] != NAME:
        raise ValueError("Template name mismatch")
    expected_services = dict(service_items(expected))
    for key, service in service_items(config):
        for field in ("source", "build", "deploy", "variables", "networking", "volumeMounts"):
            if service.get(field, {}) != expected_services[key].get(field, {}):
                raise ValueError(f"{service['name']}: {field} mismatch (values redacted)")
    metadata = read(ROOT / "marketplace-metadata.json")
    if not 45 <= len(metadata["description"]) <= 75:
        raise ValueError("Marketplace description must be 45–75 characters")
    if "id" in metadata or "code" in metadata or "distributionRepo" in metadata:
        raise ValueError("Unpublished metadata cannot claim live IDs or a standalone source")


def main():
    parser = argparse.ArgumentParser(description="Offline JSON only: no Railway/GitHub calls")
    parser.add_argument("action", choices=["restore", "audit"])
    parser.add_argument("input")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    draft = read(args.input)
    graph = read(args.graph)
    try:
        if args.action == "restore":
            if not args.output:
                raise ValueError("restore requires --output")
            output = restore(draft, graph)
            audit(output, graph)
            Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
        else:
            audit(draft, graph)
    except (ValueError, KeyError) as error:
        print(f"Offline draft {args.action} failed: {error}", file=sys.stderr)
        return 1
    print(f"Offline draft {args.action} passed; no remote operations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
