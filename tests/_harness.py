"""极简测试支架（零依赖）：check / finish。"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True      # 包内零运行态：不落 __pycache__
sys.stdout.reconfigure(encoding="utf-8")
_RESULT = []


def check(name: str, cond, detail="") -> bool:
    ok = bool(cond)
    _RESULT.append((name, ok))
    line = ("PASS  " if ok else "FAIL  ") + name
    if detail and not ok:
        line += "  | " + str(detail)[:220]
    print(line)
    return ok


def finish(title: str) -> int:
    bad = [n for n, ok in _RESULT if not ok]
    print("== %s：%d/%d 通过 ==" % (title, len(_RESULT) - len(bad), len(_RESULT)))
    return 1 if bad else 0
