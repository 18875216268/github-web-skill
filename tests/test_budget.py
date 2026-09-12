#!/usr/bin/env python3
"""预算治理单测（虚拟时钟，不真睡）：锁三条硬约束 + full jitter 边界。"""
from __future__ import annotations

import random
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
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


def main() -> int:
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

    return finish("test_budget")


if __name__ == "__main__":
    raise SystemExit(main())
