"""极简测试支架（零依赖）：路径引导 + check / finish。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True      # 包内零运行态：不落 __pycache__
sys.stdout.reconfigure(encoding="utf-8")

# 路径引导：channels/*/（方式实现，一方式一文件夹）注入 sys.path——
# gh.py 与 tests 共用同一规则；通道模块名仍为 channel_*（文件名自带前缀，import 不变）。
_PKG = Path(__file__).resolve().parents[1]
for _d in sorted((_PKG / "channels").glob("*")):
    if _d.is_dir():
        sys.path.insert(0, str(_d))

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
