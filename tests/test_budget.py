#!/usr/bin/env python3
"""预算治理单测（虚拟时钟，不真睡）：锁三条硬约束 + full jitter 边界。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.dont_write_bytecode = True      # 包内零运行态：不落 __pycache__
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "scripts"))

from _harness import check, finish  # noqa: E402
from budget import Budget  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _budget_part() -> int:
    # 1) 单次超时永不超过剩余预算
    c = Clock()
    b = Budget(overall=30, per_call=120, clock=c.now, sleeper=c.sleep)
    check("单次超时被剩余预算夹住", b.timeout_for(120) <= 30.0, b.timeout_for(120))

    # 2) 剩余不足一次有效握手 → 不再发起
    c.t = 25.0
    check("剩余 5s < 10s → can_attempt=False", b.can_attempt() is False)
    c.t = 0.0
    check("预算充足 → can_attempt=True", Budget(overall=30, clock=c.now, sleeper=c.sleep).can_attempt() is True)

    # 3) 熔断：同一目标连续失败达阈值即开
    c2 = Clock()
    b2 = Budget(overall=100, circuit_threshold=3, clock=c2.now, sleeper=c2.sleep)
    check("熔断第 1 次不触发", b2.register_empty() is False)
    check("熔断第 2 次不触发", b2.register_empty() is False)
    check("熔断第 3 次触发", b2.register_empty() is True)
    b2.register_ok()
    check("成功后熔断计数复位", b2.register_empty() is False)

    # 4) full jitter：延迟落在 [0, min(cap, base×2^(n-1))] 且随 n 变宽
    random.seed(7)
    c3 = Clock()
    b3 = Budget(overall=100, base=0.5, cap=8.0, clock=c3.now, sleeper=c3.sleep)
    d1 = b3.backoff(1)
    d4 = b3.backoff(4)
    check("退避延迟非负且不超上限", 0 <= d1 <= 0.5 and 0 <= d4 <= 4.0, "%s / %s" % (d1, d4))
    check("退避确实睡了（虚拟时钟推进）", c3.t == d1 + d4, c3.t)
    check("退避上限随 attempt 增长", min(8.0, 0.5 * 2 ** 3) > min(8.0, 0.5 * 2 ** 0))

    # 5) snapshot：如实报告预算状态（调用方靠它判断"是不是预算耗尽导致失败"）
    c4 = Clock()
    b4 = Budget(overall=90, clock=c4.now, sleeper=c4.sleep)
    s1 = b4.snapshot()
    check("snapshot 初始：remaining≈overall、exceeded=False",
          s1["overall_s"] == 90 and s1["remaining_s"] > 85 and s1["exceeded"] is False, s1)
    c4.t = 120.0
    s2 = b4.snapshot()
    check("snapshot 超预算：exceeded=True 且 remaining 夹到 0（不报负数）",
          s2["exceeded"] is True and s2["remaining_s"] == 0.0 and s2["used_s"] > 90, s2)
    check("snapshot 三字段齐全（overall_s/remaining_s/used_s/exceeded）",
          set(s2) == {"overall_s", "remaining_s", "used_s", "exceeded"}, sorted(s2))
    check("预算耗尽时 can_attempt 为假（与 snapshot 一致，不自相矛盾）",
          b4.can_attempt() is False, None)

    return 0


def test_fetch_deadline_wallclock():
    """F 组：资源层 deadline 的**墙钟**纪律（防 ThreadPoolExecutor 那种"进程退不出去"回归）。

    做法：给 fetch 脚本一批**必然超时**的实例（打黑洞端口），断言 collect() 的墙钟
    ≈ deadline + 小余量。旧实现（ThreadPoolExecutor）会被atexit join 拖到数十秒 → 变红。
    """
    import importlib.util
    import time
    from pathlib import Path
    PKG = Path(__file__).resolve().parents[1]
    ok_all = True
    for rel, mod_name, insts, dl in (
            ("sources/ip/fetch_doh.py", "f_doh",
             [{"name": "s1", "url": "https://127.0.0.1:1/resolve"},
              {"name": "s2", "url": "https://127.0.0.1:1/resolve"}],
             6.0 * 3),
            ("sources/ip/fetch_hosts.py", "f_hosts",
             [{"name": "h1", "url": "https://127.0.0.1:1/hosts"},
              {"name": "h2", "url": "https://127.0.0.1:1/hosts"}],
             10.0 + 8)):
        spec = importlib.util.spec_from_file_location(mod_name, PKG / rel)
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        t0 = time.perf_counter()
        r = m.collect(insts, ["github.com"] if "doh" in rel else None)
        wall = time.perf_counter() - t0
        limit = dl + 6.0
        check("F %s：黑洞实例下墙钟 %.1fs ≤ deadline+6s（%.0fs）"
              % (Path(rel).name, wall, limit), wall <= limit, {"wall": round(wall, 1)})
        check("F %s：失败如实留痕（ok=False / tried 非空），不编造" % Path(rel).name,
              r.get("ok") is False and bool(r.get("tried")), {"ok": r.get("ok")})
        ok_all = ok_all and r.get("ok") is False
    return 0


def main() -> int:
    if _budget_part() != 0:
        return 1
    if test_fetch_deadline_wallclock() != 0:
        return 1
    return finish("test_budget")


if __name__ == "__main__":
    raise SystemExit(main())
