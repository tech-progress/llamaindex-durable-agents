#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input="${1:?Usage: audit-template.sh INPUT_JSON (offline only)}"
graph="$(mktemp)"
trap 'rm -f "$graph"' EXIT
(cd "$root" && ./node_modules/.bin/railway-iac-ts .railway/railway.ts) >"$graph"
python3 "$root/scripts/draft.py" audit "$input" --graph "$graph"
