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
TIMEOUT = 10.0         # 单端点探测**总预算**（秒）——双栈/污染多地址不再 6s×N 累加


def endpoints() -> list:
    """读取 kinds.ssh.endpoints（数据与探测解耦：改 sources.json 即生效）。

    源文件缺失/损坏时返回 []（结构化降级，不抛异常——stdout JSON 契约优先）。
    """
    try:
        d = json.loads(SRC_F.read_text(encoding="utf-8"))
        return d["kinds"]["ssh"]["endpoints"]
    except (OSError, ValueError, KeyError):
        return []


def _connect_capped(host: str, port: int, timeout: float) -> dict:
    """带总预算封顶的 TCP 连接：逐地址预算 = 剩余总预算（双栈/污染多地址不累加）。

    返回 {"ok": bool, "ms": 总耗时, "errs": [逐地址失败记录（IP:类型/预算耗尽）]}。
    github.com/ssh.github.com 正常只发布 A 记录（单地址）——封顶针对的是
    DNS 污染返回多个假地址的目标环境（正是本技能的主战场）。
    """
    t0 = time.monotonic()
    deadline = t0 + timeout
    errs, n_tried = [], 0
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return {"ok": False, "ms": round((time.monotonic() - t0) * 1000),
                "errs": ["getaddrinfo:%s" % type(exc).__name__]}
    for af, st, proto, _cn, sa in infos:
        remain = deadline - time.monotonic()
        if remain <= 0:
            errs.append("预算耗尽@%s" % (sa[0],))
            continue
        s = None
        try:
            s = socket.socket(af, st, proto)
            s.settimeout(remain)
            s.connect(sa)
            ms = round((time.monotonic() - t0) * 1000)
            return {"ok": True, "ms": ms, "errs": errs, "addr": sa[0], "tried": n_tried}
        except OSError as exc:
            n_tried += 1
            errs.append("%s:%s" % (sa[0], type(exc).__name__))
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
    return {"ok": False, "ms": round((time.monotonic() - t0) * 1000), "errs": errs,
            "tried": n_tried}


def probe(timeout: float = TIMEOUT) -> dict:
    """对全部官方端点做纯 TCP 连通性探测（零凭证、事实记录、不做性能结论）。

    每个端点探测总耗时 ≤ timeout（多地址预算封顶，不随地址数累加）。
    返回 {"ok": 任一端点可达, "endpoints": [{name, host, port, ok, ms[, errs]}]}。
    """
    eps = endpoints()
    if not eps:
        return {"ok": False, "endpoints": [],
                "err": "SSH 端点源读取失败（kinds.ssh 缺失或损坏）"}
    out = []
    for ep in eps:
        r = _connect_capped(ep.get("host", "?"), int(ep.get("port", 0)), timeout)
        rec = {"name": ep.get("name", "?"), "host": ep.get("host", "?"),
               "port": ep.get("port", "?"), "ok": r["ok"], "ms": r["ms"]}
        if r.get("errs"):
            rec["errs"] = r["errs"][:6]          # 事实记录，截断防爆量
        out.append(rec)
    return {"ok": any(o["ok"] for o in out), "endpoints": out}


def status() -> dict:
    """CLI / diag 用的完整状态（事实记录）。"""
    r = probe()
    doors = "、".join("%s(%s)" % (e["name"], "✓" if e["ok"] else "✗") for e in r["endpoints"])
    return {"action": "ssh.status", **r, "channel": "ssh", "third_party": False,
            "detail": "SSH 端点连通性：%s" % doors,
            "note": "纯 TCP 探测，零凭证；实际 git 走 SSH 需用户自行配置 key（凭证归用户，本通道零接触）"}
