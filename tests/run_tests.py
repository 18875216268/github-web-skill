#!/usr/bin/env python3
"""测试总入口：python tests/run_tests.py [--offline]

--offline 跳过真机只读冒烟（无网络/不想出网时用）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TESTS = Path(__file__).resolve().parent
SUITE = ["test_spec_and_docs.py", "test_quality.py", "test_probe.py", "test_budget.py",
         "test_routing.py", "test_hosts_marker.py"]
SMOKE = "test_readonly_smoke.py"


def main() -> int:
    offline = "--offline" in sys.argv
    files = SUITE + ([] if offline else [SMOKE])
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}   # 子进程也不落 __pycache__
    failed = []
    for f in files:
        p = subprocess.run([sys.executable, str(TESTS / f)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=1800, env=env)
        print(p.stdout, end="")
        if p.returncode != 0:
            failed.append(f)
            print("  (stderr) " + (p.stderr or "")[-400:])
    print("\n==== 总入口：%d/%d 个测试文件通过%s ====" % (
        len(files) - len(failed), len(files), "（已跳过冒烟）" if offline else ""))
    for f in failed:
        print("  FAIL:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
