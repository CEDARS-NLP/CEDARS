#!/usr/bin/env python3
"""Dependency audit ratchet: known vulnerabilities may not increase past scripts/audit-baseline.json.

Usage: scripts/audit_ratchet.py [--update]   (--update only ever lowers the baseline)
"""
import json
import subprocess
import sys
from pathlib import Path

BASELINE = Path("scripts/audit-baseline.json")


def python_vulns() -> int:
    req = subprocess.run(["uv", "export", "--no-hashes", "--no-emit-project", "-q"],
                         cwd="backend", capture_output=True, text=True, check=True).stdout
    Path("/tmp/audit-req.txt").write_text(req)
    out = subprocess.run(["uvx", "pip-audit", "-r", "/tmp/audit-req.txt", "--disable-pip", "--no-deps",
                          "-f", "json"], capture_output=True, text=True).stdout
    deps = json.loads(out)["dependencies"]
    return sum(len(d.get("vulns", [])) for d in deps)


def npm_high() -> int:
    out = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd="frontend",
                         capture_output=True, text=True).stdout
    meta = json.loads(out)["metadata"]["vulnerabilities"]
    return meta.get("high", 0) + meta.get("critical", 0)


def main() -> int:
    now = {"python": python_vulns(), "npm_high_or_critical": npm_high()}
    base = json.loads(BASELINE.read_text())
    if "--update" in sys.argv:
        lowered = {k: min(base[k], now[k]) for k in base}
        BASELINE.write_text(json.dumps(lowered, indent=2) + "\n")
        print("baseline now", lowered)
        return 0
    worse = {k: (now[k], base[k]) for k in base if now[k] > base[k]}
    print("audit:", now, "baseline:", base)
    if worse:
        print("FAIL: new vulnerabilities (now, allowed):", worse)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
