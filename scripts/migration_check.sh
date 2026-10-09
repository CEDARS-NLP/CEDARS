#!/usr/bin/env bash
# Migration safety net against an EMPTY Postgres at $CEDARS_DATABASE_URL (asyncpg URL):
# single head, upgrade -> downgrade -1 -> upgrade, and model-vs-migration drift may not grow.
# Baseline lives in backend/.alembic-drift-baseline (number of drift markers in `alembic check` output; lower it as drift is fixed).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/backend"
: "${CEDARS_DATABASE_URL:?set CEDARS_DATABASE_URL to an empty Postgres}"
A="uv run --quiet alembic"

heads=$($A heads | grep -c '(head)' || true)
[ "$heads" = "1" ] || { echo "FAIL: expected 1 alembic head, found $heads"; $A heads; exit 1; }
$A upgrade head >/dev/null
$A downgrade -1 >/dev/null
$A upgrade head >/dev/null
echo "ok   single head, upgrade/downgrade/upgrade round trip"

out=$($A check 2>&1 || true)
if echo "$out" | grep -q "No new upgrade operations"; then ops=0
else ops=$(echo "$out" | grep -o -E "\('(add|remove|modify)_[a-z_]+'," | wc -l | tr -d ' '); fi
allowed=$(cat .alembic-drift-baseline)
if [ "$ops" -gt "$allowed" ]; then
  echo "FAIL: model/migration drift grew: $ops operations, baseline allows $allowed. Add the migration (or fix the model)."
  echo "$out" | grep -o -E "\('(add|remove|modify)_[a-z_]+', [A-Za-z]+\('[a-zA-Z_0-9]+'" | sort | uniq
  exit 1
fi
echo "ok   drift $ops operations (baseline $allowed)"
