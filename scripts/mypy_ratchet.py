#!/usr/bin/env python3
"""Fail if mypy reports more errors than backend/.mypy-baseline allows. Run from the repo root.

Usage: scripts/mypy_ratchet.py [--update]   (--update lowers the baseline after a cleanup)
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "backend" / ".mypy-baseline"


def current_errors() -> int:
    out = subprocess.run(
        ["uv", "run", "--directory", str(ROOT / "backend"), "mypy", "app"],
        capture_output=True, text=True,
    ).stdout
    m = re.search(r"Found (\d+) errors?", out)
    return int(m.group(1)) if m else 0


def main() -> int:
    errors = current_errors()
    allowed = int(BASELINE.read_text())
    if "--update" in sys.argv:
        if errors > allowed:
            print(f"mypy: {errors} errors > baseline {allowed}; refusing to raise it")
            return 1
        BASELINE.write_text(f"{errors}\n")
        print(f"mypy baseline set to {errors}")
        return 0
    if errors > allowed:
        print(f"mypy: {errors} errors, baseline allows {allowed}. Fix the new type errors.")
        return 1
    print(f"mypy: {errors} errors (baseline {allowed})" + ("; run --update to lower it" if errors < allowed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
