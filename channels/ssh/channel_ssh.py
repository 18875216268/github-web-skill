"""通道 ssh：SSH 传输官方端点探测（单开源类 kinds.ssh；不进自动降级链）。

职责边界（单开铁律）：
- 只消费 sources.json 的 kinds.ssh（2 个官方端点），与 ip/mirror/cdn 零借用；
- 只做纯 TCP 连通性探测——零凭证：不生成、不读取、不存储用户的 SSH key；
- 不进自动降级链（SSH 只承载 git 操作，不能替 HTTPS URL 取 raw/release）——
  产出是"传输健康事实"：diag --full 的 ssh_probe、失败路径的 offers、独立 CLI `gh.py ssh --status`。

双模语义（与文档 §9 对齐）：
- 探测模式：零凭证，任何用户可跑（看门开没开）；
- 使用模式：用户自行配置 key + SSH 地址后，git 传输自然走 SSH——本通道只提供健康依据，
  凭证由 git/ssh 进程直接使用用户自己的 agent，本技能零接触。
"""
from __future__ import annotations

import json
import socket
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[2]      # channels/ssh/ → 包根（两级）
SRC_F = PKG / "sources" / "sources.json"
TIMEOUT = 6.0          # 单端点 TCP 连接超时（秒）——与治理层单条探测超时同级


def endpoints() -> list:
    """读取 kinds.ssh.endpoints（数据与探测解耦：改 sources.json 即生效）。"""
    d = json.loads(SRC_F.read_text(encoding="utf-8"))
    return d["kinds"]["ssh"]["endpoints"]


def probe(timeout: float = TIMEOUT) -> dict:
    """对全部官方端点做纯 TCP 连通性探测（零凭证、事实记录、不做性能结论）。

    返回 {"ok": 任一端点可达, "endpoints": [{name, host, port, ok, ms[, err]}]}。
    """
    out = []
    for ep in endpoints():
        t0 = time.perf_counter()
        ok, err = False, ""
        try:
            with socket.create_connection((ep["host"], ep["port"]), timeout=timeout):
                ok = True
        except OSError as exc:
            err = type(exc).__name__
        rec = {"name": ep["name"], "host": ep["host"], "port": ep["port"],
               "ok": ok, "ms": round((time.perf_counter() - t0) * 1000)}
        if err:
            rec["err"] = err
        out.append(rec)
    return {"ok": any(o["ok"] for o in out), "endpoints": out}


def status() -> dict:
    """CLI / diag 用的完整状态（事实记录）。"""
    r = probe()
    doors = "、".join("%s(%s)" % (e["name"], "✓" if e["ok"] else "✗") for e in r["endpoints"])
    return {"action": "ssh.status", **r, "channel": "ssh", "third_party": False,
            "detail": "SSH 端点连通性：%s" % doors,
            "note": "纯 TCP 探测，零凭证；实际 git 走 SSH 需用户自行配置 key（凭证归用户，本通道零接触）"}
