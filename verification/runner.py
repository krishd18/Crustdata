"""V-runner: runs V1 (contract), V2/V4/V7 (e2e golden + rubric parity + number lock), V5 (kill trials, Mailpit) and
writes reports/backtest/summary.md. Usage: python -m verification.runner --all [--trials 10]"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> tuple[bool, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode == 0, (p.stdout + p.stderr).strip().splitlines()[-1] if (p.stdout + p.stderr).strip() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--agent")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--e2e", action="store_true")
    ap.add_argument("--repeat", type=int, default=3)
    a = ap.parse_args()
    py = sys.executable
    checks = [("V1 contract (15 agents, edge payloads)", [py, "-m", "pytest", "-q", "tests/contract"]),
              ("Unit (core, rubric, verdict safety, Claude fail-closed/fallback)", [py, "-m", "pytest", "-q", "tests/unit"]),
              ("V2/V4/V7 golden e2e + rubric parity + 3× determinism", [py, "-m", "pytest", "-q", "tests/e2e"]),
              ("V7 reference scorer", [py, "tools/rubric_check.py"]),
              ("Secrets in cassettes", [py, "tools/scrub_cassettes.py"])]
    if a.all:
        checks.append((f"V5 kill trials ({a.trials}, Mailpit)", [py, "tools/kill_demo.py", "--trials", str(a.trials)]))
    rows, ok_all = [], True
    for name, cmd in checks:
        ok, last = run(cmd)
        ok_all &= ok
        rows.append(f"| {name} | {'✅ pass' if ok else '❌ FAIL'} | {last[:120]} |")
    out = ROOT / "reports" / "backtest"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.md").write_text(f"# Back-test summary · {time.strftime('%Y-%m-%d %H:%M')}\n\n| Check | Status | Last line |\n|---|---|---|\n" + "\n".join(rows) + "\n")
    print("\n".join(rows))
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
