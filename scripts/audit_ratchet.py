#!/usr/bin/env python3
"""Dependency audit ratchet: fail on any vulnerability ID not listed in scripts/audit-baseline.json.

Usage: scripts/audit_ratchet.py [--update]
  --update  rewrite the baseline to exactly today's IDs (use after fixing some, or to accept a new one on purpose)
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "scripts" / "audit-baseline.json"


def python_vulns() -> set[str]:
    req = subprocess.run(["uv", "export", "--no-hashes", "--no-emit-project", "-q"],
                         cwd=ROOT / "backend", capture_output=True, text=True, check=True).stdout
    Path("/tmp/audit-req.txt").write_text(req)
    out = subprocess.run(["uvx", "pip-audit", "-r", "/tmp/audit-req.txt", "--disable-pip", "--no-deps",
                          "-f", "json"], capture_output=True, text=True).stdout
    return {f"{d['name']} {v['id']}" for d in json.loads(out)["dependencies"] for v in d.get("vulns", [])}


def npm_vulns() -> set[str]:
    out = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd=ROOT / "frontend",
                         capture_output=True, text=True).stdout
    vulns = json.loads(out).get("vulnerabilities", {})
    return {name for name, v in vulns.items() if v.get("severity") in ("high", "critical")}


def main() -> int:
    now = {"python": sorted(python_vulns()), "npm_high_or_critical": sorted(npm_vulns())}
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(now, indent=1) + "\n")
        print({k: len(v) for k, v in now.items()}, "written to baseline")
        return 0
    base = json.loads(BASELINE.read_text())
    new = {k: sorted(set(now[k]) - set(base[k])) for k in now}
    print("audit:", {k: len(v) for k, v in now.items()}, "baseline:", {k: len(v) for k, v in base.items()})
    if any(new.values()):
        print("FAIL: vulnerabilities not in the baseline (fix them, or run --update to accept on purpose):")
        for k, v in new.items():
            for item in v:
                print(f"  [{k}] {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
