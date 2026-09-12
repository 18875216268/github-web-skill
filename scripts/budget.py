"""预算治理：单次超时 + 整体 deadline + 熔断 + full jitter 退避。

两条必须分清的语义（混用会既慢又无效）：
  failover 换目标 —— 每次换一个新目标，不需要退避；
  retry 同目标   —— 同一目标反复打，必须退避并熔断。
时钟与睡眠可注入（虚拟时钟即可确定性复测三条硬约束）。
"""
from __future__ import annotations

import random
import time


class Budget:
    def __init__(self, overall=180.0, per_call=120.0, min_effective=10.0,
                 circuit_threshold=3, base=0.5, cap=8.0, clock=time.monotonic, sleeper=time.sleep):
        self.deadline = clock() + float(overall)
        self.per_call = float(per_call)
        self.min_effective = float(min_effective)
        self.circuit_threshold = int(circuit_threshold)
        self._clock, self._sleep = clock, sleeper
        self._base, self._cap = base, cap
        self._empty_streak = 0

    # ---------- 时间 ----------
    def remaining(self) -> float:
        return self.deadline - self._clock()

    def can_attempt(self) -> bool:
        """剩余预算不足以完成一次有效握手时不再发起新尝试。"""
        return self.remaining() >= self.min_effective

    def timeout_for(self, want: float) -> float:
        """单次超时永远不超过剩余预算。"""
        return max(1.0, min(float(want), self.remaining()))

    # ---------- 熔断（同一目标连续失败） ----------
    def register_empty(self) -> bool:
        """记录一次"拿不到候选"；返回 True 表示熔断开启（停止本次加速）。"""
        self._empty_streak += 1
        return self._empty_streak >= self.circuit_threshold

    def register_ok(self) -> None:
        self._empty_streak = 0

    # ---------- 退避 ----------
    def backoff(self, attempt: int) -> float:
        """full jitter：均匀采样 [0, min(cap, base × 2^(attempt-1))]；随后睡眠。"""
        ceiling = min(self._cap, self._base * (2 ** max(0, attempt - 1)))
        delay = random.uniform(0, ceiling)
        self._sleep(delay)
        return delay
