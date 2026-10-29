#!/usr/bin/env bash
# Migration safety net against an EMPTY Postgres at $CEDARS_DATABASE_URL (asyncpg URL):
# Each split history: single head, upgrade -> downgrade -1 -> upgrade, and drift may not grow.
# Returns the scratch database to base between histories and after checking them.
# Baseline lives in backend/.alembic-drift-baseline (number of drift markers in `alembic check` output; lower it as drift is fixed).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)/backend"
: "${CEDARS_DATABASE_URL:?set CEDARS_DATABASE_URL to an empty Postgres}"
A="uv run --quiet alembic"

ops=0
for history in global project; do
  config="${history}-alembic.ini"
  heads=$($A -c "$config" heads | grep -c '(head)' || true)
  [ "$heads" = "1" ] || { echo "FAIL: expected 1 $history alembic head, found $heads"; $A -c "$config" heads; exit 1; }
  $A -c "$config" upgrade head >/dev/null
  $A -c "$config" downgrade -1 >/dev/null
  $A -c "$config" upgrade head >/dev/null
  echo "ok   $history single head, upgrade/downgrade/upgrade round trip"

  if out=$($A -c "$config" check 2>&1); then
    history_ops=0
  else
    history_ops=$(echo "$out" | { grep -o -E "\('(add|remove|modify)_[a-z_]+'," || true; } | wc -l | tr -d ' ')
    if [ "$history_ops" -eq 0 ]; then
      echo "FAIL: $history alembic check failed"
      echo "$out"
      exit 1
    fi
    echo "$out"
  fi
  ops=$((ops + history_ops))
  $A -c "$config" downgrade base >/dev/null
done
allowed=$(cat .alembic-drift-baseline)
if [ "$ops" -gt "$allowed" ]; then
  echo "FAIL: model/migration drift grew: $ops operations, baseline allows $allowed. Add the migration (or fix the model)."
  exit 1
fi
echo "ok   drift $ops operations (baseline $allowed)"
