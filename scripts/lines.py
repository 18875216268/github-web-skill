"""治理层常量（唯一事实源）。

方式各自的**数据清单**已归位到资源层（sources/mirror/static/mirror.json、
sources/cdn/static/cdn.json、IP 供给走 sources/hub.py）——本文件只保留跨方式共用的治理常量：
hosts 严格校验目标、并发探测参数、预算与连接超时。
数值依据：2026-09-11 真机实测（6 域 IP 逐条拨测 / CDN·镜像池逐源验证）。
"""
from __future__ import annotations

# ---------- hosts 写入前的严格校验目标（域 → 已知小文件） ----------
# 为什么需要：根路径响应是弱判据——2026-09-11 实测 raw 的 185.199.111.133 根路径 200、
# 真实取文件却 000（10s 超时）。写进系统解析的 IP 必须"能真正取到内容"。
STRICT_PROBE_URLS = {
    "raw.githubusercontent.com": "https://raw.githubusercontent.com/github/gitignore/main/README.md",
}

PROBE = {
    "workers": 7,            # 并发度（标准库线程；每条探测都是独立 curl/git 子进程）
    "timeout": 4.0,          # 单条探测超时（秒）——快速定位不通，立即换源
    "deadline": 6.0,         # 一轮探测整体上限；到点用已返回的最优者
    "fresh_ok_within": 300,  # 账本里"最近成功过"的源直接真取（免探测）的时间窗
    "cooldown_base": 60.0,   # 失败冷却基数：60s × 2^(连败-1)，封顶
    "cooldown_max": 3600.0,  # 冷却封顶（到期自动半开重试；永不删除）
}

DEFAULT_BUDGET = {"get": 60.0, "git_read": 180.0, "per_call": 120.0,
                  "min_effective": 10.0, "circuit_threshold": 3}   # diag 不设整体预算：各步自带超时
PIN_CONNECT_TIMEOUT = 4.0             # 代理内单 IP 连接超时（实测 12s 太慢会吃掉预算）
