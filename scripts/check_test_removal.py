#!/usr/bin/env python3
"""Fail if a PR deletes tests or adds skip/xfail markers. Override with the `ci-allow-test-removal` label.

Usage: scripts/check_test_removal.py <base-ref>      (env PR_LABELS: comma-separated labels)
"""
import os
import re
import subprocess
import sys

base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
if "ci-allow-test-removal" in os.environ.get("PR_LABELS", ""):
    print("test-removal check skipped by label")
    sys.exit(0)

diff = subprocess.run(
    ["git", "diff", "-U0", f"{base}...HEAD", "--", "backend/tests", "frontend/src", "e2e"],
    capture_output=True, text=True, check=True,
).stdout

problems = []
for line in diff.splitlines():
    if re.match(r"^-\s*(async\s+)?def test_|^-\s*(it|test)\(", line):
        problems.append(f"removed test: {line[1:].strip()}")
    if re.match(r"^\+.*(pytest\.mark\.(skip|xfail)|pytest\.skip\(|\b(it|test|describe)\.(skip|only|fixme)\()", line):
        problems.append(f"added skip/xfail/only: {line[1:].strip()}")

if problems:
    print("Tests were weakened. Add the `ci-allow-test-removal` label if intentional:")
    print("\n".join(f"  - {p}" for p in problems))
    sys.exit(1)
print("no tests removed or skipped")
