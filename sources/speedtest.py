"""统一测速器（D13）：无状态纯评估器——并发测 → 升序返回全部。

只测+只排：不编排（hub 的事）、不拉取（fetch 的事）、不落盘、不写账本（probe 历史职能无关）、
不截断（Top-N 由 hub 定）。并发收口**复用治理层 probe.race**（零重复实现）。

策略注入（数据驱动）：测速方式由 sources.json 的 kinds.<类>.speedtest 声明、hub 注入——
本模块只认执行器，不认识具体大类名（新增大类零改码）：
  tcp  → TCP 连接测速（socket 级，毫秒精度；port 由策略声明，默认 443）
  head → HTTP HEAD 探测（curl 子进程，清代理环境；URL 由调用方渲染好传入）

三闸并存：speedtest（现在谁快）/ verify（真的能用吗）/ probe（上次谁表现好）。
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402
import probe as _probe  # noqa: E402

TCP_TIMEOUT = 3.0
HEAD_TIMEOUT = 4.0
WORKERS = 32
DEADLINE = 8.0                      # 一轮测速总上限——到点收口用已得结果


def _tcp_ms(ip: str, timeout: float = TCP_TIMEOUT, port: int = 443) -> dict:
    """TCP 连接测速（socket 级；端口由策略声明）。"""
    t0 = time.perf_counter()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return {"ok": True, "latency": round((time.perf_counter() - t0) * 1000)}
    except Exception:
        return {"ok": False}


def _head_ms(url: str, timeout: float = HEAD_TIMEOUT) -> dict:
    """HTTP HEAD 探测（curl 子进程，清代理环境）。"""
    t0 = time.perf_counter()
    args = env_guard.curl_base(timeout) + ["-I", "-L", "--max-redirs", "3", "-o",
                                           "NUL" if sys.platform == "win32" else "/dev/null",
                                           "-w", "%{http_code}", url]
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env_guard.clean_env(), timeout=timeout + 3)
    except Exception:
        return {"ok": False}
    code = ((p.stdout or "000").strip().splitlines() or ["000"])[-1]
    ok = code != "000"
    return {"ok": ok, "latency": round((time.perf_counter() - t0) * 1000) if ok else None}


def _measure_one(c: dict, strat: dict) -> dict:
    if strat.get("method") == "tcp":
        return _tcp_ms(c["ip"], port=int(strat.get("port") or 443))
    return _head_ms(c["url"])                     # method=head（hub 已校验 method 合法性）


def measure_all(candidates: list, strategies: dict, deadline: float = DEADLINE) -> list:
    """并发测全部候选 → 升序返回全部测通的（失败丢弃、超时补占位即弃）。

    candidates 元素：{"kind":"ip","ip":…,"domain":…,"sources":[…]}
                   ｜ {"kind":"mirror"/"cdn",…,"url":…}（其余字段原样透传）。
    strategies：{kind: kinds.<类>.speedtest 节}——测速方式的数据声明，hub 注入。
    返回：同元素 + {"latency": ms}，按 (kind, latency) 升序。
    """
    if not candidates:
        return []
    tasks = []
    for i, c in enumerate(candidates):
        strat = strategies.get(c.get("kind")) or {}
        tasks.append((str(i), (lambda c=c, s=strat: _measure_one(c, s))))
    res = _probe.race(tasks, workers=WORKERS, deadline=deadline)
    out = []
    for key, ok, val, _ms in res:
        if not ok:
            continue                                 # 测不通：丢弃（诚实——不进清单）
        c = dict(candidates[int(key)])
        c["latency"] = (val or {}).get("latency")
        out.append(c)
    out.sort(key=lambda x: (x["kind"], x.get("latency") or 10 ** 9))
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = json.loads(sys.stdin.read() or "{}") if not sys.argv[1:] else \
        json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    strat = {k: (node or {}).get("speedtest") or {}
             for k, node in json.loads((_PKG / "sources" / "sources.json")
                                       .read_text(encoding="utf-8"))["kinds"].items()}
    print(json.dumps(measure_all(data.get("candidates") or [], strategies=strat),
                     ensure_ascii=False, indent=2))
