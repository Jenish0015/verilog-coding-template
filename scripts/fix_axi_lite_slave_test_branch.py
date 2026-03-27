#!/usr/bin/env python3
"""
Fix axi_lite_slave_test: it must contain the SAME RTL as baseline (stub) plus only
tests/test_axi_lite_slave_hidden.py. If test branch has golden/full RTL, test.patch
reimplements the DUT when applied and hidden tests pass — validation fails with
"Test patch did not cause tests to fail".

Usage (from repo root, with network + git push access):
  .venv/bin/python scripts/fix_axi_lite_slave_test_branch.py
  .venv/bin/python scripts/fix_axi_lite_slave_test_branch.py --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/Jenish0015/axi_lite_slave.git"
BASELINE = "axi_lite_slave_baseline"
TEST = "axi_lite_slave_test"
RTL = Path("sources/axi_lite_slave.sv")


def run(cmd: list[str], cwd: Path) -> None:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(p.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    work = root / "_axi_lite_slave_work"
    if work.exists():
        shutil.rmtree(work)

    print("clone...", flush=True)
    run(["git", "clone", REPO_URL, str(work)], cwd=root)
    run(["git", "fetch", "origin", BASELINE, TEST], cwd=work)
    run(["git", "checkout", TEST], cwd=work)

    baseline_file = work / "baseline_rtl.sv"
    subprocess.run(
        ["git", "show", f"origin/{BASELINE}:{RTL}"],
        cwd=work,
        check=True,
        stdout=open(baseline_file, "wb"),
    )
    shutil.copyfile(baseline_file, work / RTL)
    baseline_file.unlink()

    run(["git", "add", str(RTL)], cwd=work)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=work).returncode != 0:
        run(
            ["git", "commit", "-m", "test branch: match baseline RTL; tests only beyond baseline"],
            cwd=work,
        )
    else:
        print("No RTL change — test branch already matches baseline.", flush=True)
        return

    if args.dry_run:
        print(f"Dry-run OK — inspect {work}, then: git push origin {TEST}", flush=True)
        return

    run(["git", "push", "origin", TEST], cwd=work)
    print(f"Pushed {TEST}. Rebuild Docker (bump Dockerfile ENV random) and re-run imagectl3.", flush=True)


if __name__ == "__main__":
    main()
