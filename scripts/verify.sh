#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
mode="${1:---static}"
[[ "$mode" == --static || "$mode" == --local ]] || { echo 'Usage: verify.sh [--static|--local]' >&2; exit 1; }
required=(.env.example .dockerignore .gitignore .railway/railway.ts Dockerfile compose.yaml pyproject.toml uv.lock package.json bun.lock VERSION CHANGELOG.md README.md MARKETPLACE.md LICENSE SUPPORT.md UPGRADE.md template-defaults.json template-descriptions.json template-networking.json template-volumes.json marketplace-metadata.json start.sh scripts/smoke.py scripts/restore-template-draft.sh scripts/audit-template.sh)
for file in "${required[@]}"; do test -f "$file" || { echo "Missing $file" >&2; exit 1; }; done
version="$(cat VERSION)"
[[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
rg -q "^## \[${version//./\\.}\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" CHANGELOG.md
for file in README.md UPGRADE.md; do rg -Fq "current template release is \`v$version\`" "$file"; done
for heading in '# Deploy and Host' '## About Hosting' '## Why Deploy' '## Common Use Cases' '## Dependencies for' '### Deployment Dependencies'; do rg -Fq "$heading" MARKETPLACE.md; done
timeout 120 uv lock --check
timeout 120 bun install --frozen-lockfile >/dev/null
timeout 120 uv sync --frozen >/dev/null
timeout 60 uv run --frozen python -m unittest discover -s tests -v
for file in scripts/*.sh; do bash -n "$file"; done
export API_TOKEN="$(openssl rand -hex 24)" POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export PROPOSAL_MODE=deterministic OPENAI_API_KEY=''
docker compose -p rt-llama-cb5c13c4 config --quiet
scratch="$(mktemp -d)"
owns_resources=false
cleanup() {
  local result=$?
  if [[ "$owns_resources" == true ]]; then
    if (( result != 0 )); then
      timeout 15 docker compose -p rt-llama-cb5c13c4 logs --no-color --tail 80 api | sed -E "s/${API_TOKEN}/<REDACTED>/g; s/${POSTGRES_PASSWORD}/<REDACTED>/g" >&2 || true
    fi
    if ! timeout 90 docker compose -p rt-llama-cb5c13c4 down --volumes --remove-orphans >/dev/null 2>&1; then
      echo 'Own-resource cleanup failed or timed out' >&2
      result=1
    fi
    local remaining_containers remaining_volumes remaining_networks
    remaining_containers="$(timeout 15 docker ps -aq --filter label=com.docker.compose.project=rt-llama-cb5c13c4)" || result=1
    remaining_volumes="$(timeout 15 docker volume ls -q --filter label=com.docker.compose.project=rt-llama-cb5c13c4)" || result=1
    remaining_networks="$(timeout 15 docker network ls -q --filter label=com.docker.compose.project=rt-llama-cb5c13c4)" || result=1
    if [[ -n "$remaining_containers$remaining_volumes$remaining_networks" ]]; then
      echo 'Own resources remain after cleanup; gate failed' >&2
      result=1
    elif (( result == 0 )); then
      echo 'PASS: zero own containers, volumes and networks after bounded cleanup'
    fi
  fi
  rm -rf "$scratch"
  exit "$result"
}
trap cleanup EXIT
./node_modules/.bin/railway-iac-ts .railway/railway.ts >"$scratch/graph.json"
uv run --frozen python - "$scratch" <<'PY'
import json, sys
from pathlib import Path
from tests.test_draft import DraftTests
root = Path(sys.argv[1])
root.joinpath('contaminated.json').write_text(json.dumps(DraftTests().contaminated()))
PY
if ./scripts/audit-template.sh "$scratch/contaminated.json" 2>"$scratch/negative.log"; then
  echo 'Contaminated draft incorrectly passed audit' >&2; exit 1
fi
./scripts/restore-template-draft.sh "$scratch/contaminated.json" "$scratch/restored.json"
./scripts/audit-template.sh "$scratch/restored.json"
TEMPLATE_SOURCE_REPO=example/explicit-fork TEMPLATE_SOURCE_BRANCH=release-v2 TEMPLATE_SOURCE_ROOT=/ ./node_modules/.bin/railway-iac-ts .railway/railway.ts >"$scratch/override.json"
jq -e '.graph.resources[] | select(.name=="LlamaIndex API") | .source.repo=="example/explicit-fork" and .source.branch=="release-v2" and .source.rootDirectory=="/" and .build.watchPatterns==["/**"]' "$scratch/override.json" >/dev/null
if TEMPLATE_SOURCE_BRANCH=release/v1 ./node_modules/.bin/railway-iac-ts .railway/railway.ts >"$scratch/invalid.json" 2>&1; then echo 'Slash branch was accepted' >&2; exit 1; fi
echo 'PASS: static contract, unit suite, contaminated restoration/negative audit and source overrides (offline)'
[[ "$mode" == --local ]] || exit 0
existing_containers="$(timeout 15 docker ps -aq --filter label=com.docker.compose.project=rt-llama-cb5c13c4)"
existing_volumes="$(timeout 15 docker volume ls -q --filter label=com.docker.compose.project=rt-llama-cb5c13c4)"
existing_networks="$(timeout 15 docker network ls -q --filter label=com.docker.compose.project=rt-llama-cb5c13c4)"
if [[ -n "$existing_containers$existing_volumes$existing_networks" ]]; then
  echo 'Isolated verification project already exists; refusing to alter pre-existing resources' >&2
  exit 1
fi
owns_resources=true
timeout 300 docker compose -p rt-llama-cb5c13c4 build --no-cache
timeout 150 docker compose -p rt-llama-cb5c13c4 up -d --wait --wait-timeout 120
for pattern in test_workflow.py test_security.py test_provider.py; do
  timeout 60 docker compose -p rt-llama-cb5c13c4 exec -T api /app/.venv/bin/python -m unittest discover -s tests -p "$pattern" -v
done
timeout 60 docker compose -p rt-llama-cb5c13c4 exec -T -e TEST_DATABASE_URL="postgresql://workflows:${POSTGRES_PASSWORD}@postgres:5432/workflows" api /app/.venv/bin/python -m unittest discover -s tests -p test_ledger_integration.py -v
sleep 10
echo 'Idle snapshot (10 seconds after application tests, before workflow smoke):'
timeout 20 docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "$(timeout 15 docker compose -p rt-llama-cb5c13c4 ps -q api)" "$(timeout 15 docker compose -p rt-llama-cb5c13c4 ps -q postgres)"
timeout 420 ./scripts/smoke.sh
sleep 10
echo 'Post-workload snapshot (10 seconds after smoke):'
timeout 20 docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' "$(timeout 15 docker compose -p rt-llama-cb5c13c4 ps -q api)" "$(timeout 15 docker compose -p rt-llama-cb5c13c4 ps -q postgres)"
echo 'PASS: clean image build, Railway-equivalent start, app tests, SQL replay test and crash/approval smoke'
