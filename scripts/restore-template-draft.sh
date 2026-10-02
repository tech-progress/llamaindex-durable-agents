#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input="${1:?Usage: restore-template-draft.sh INPUT_JSON OUTPUT_JSON}"
output="${2:?Usage: restore-template-draft.sh INPUT_JSON OUTPUT_JSON}"
graph="$(mktemp)"
trap 'rm -f "$graph"' EXIT
(cd "$root" && ./node_modules/.bin/railway-iac-ts .railway/railway.ts) >"$graph"
python3 "$root/scripts/draft.py" restore "$input" --graph "$graph" --output "$output"
