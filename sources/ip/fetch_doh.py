"""获取方式②：DoH 解析源——DNS 协议查询（异构于 hosts 清单拉取）→ 候选映射。

统一纪律（D15）：实例清单由 collect 注入（sources.json 的 ways.doh.sources）→ 并发查询 →
单服务器失败跳过（tried 留痕）→ 多服务器结果**合并去重**（候选宁多勿漏，测速会筛）。
查询目标域 = sources.json 的 kinds.ip.domains（大类级共享全量域清单）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parents[1]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402
import probe as _probe  # noqa: E402   # 统一并发原语（守护线程 + deadline 收手）

WAY = "doh"
IP_RE = re.compile(r'"data":"(\d+\.\d+\.\d+\.\d+)"')
TIMEOUT = 6.0
WORKERS_DOMAIN = 16


def _query(server: dict, domain: str) -> list:
    """单服务器查单域 → 去重 IP 列表（失败返回空）。

    统一带 `accept: application/dns-json`——/resolve 形式（阿里/360）与 /dns-query 形式
    （doh.pub）都接受该头，两类端点一条代码路径。
    """
    args = env_guard.curl_base(TIMEOUT) + ["-H", "accept: application/dns-json",
                                           "-fsSL", "%s?name=%s&type=A" % (server["url"], domain)]
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env_guard.clean_env(), timeout=TIMEOUT + 4)
    except Exception:
        return []
    seen, out = set(), []
    for ip in IP_RE.findall(p.stdout or ""):
        if ip not in seen:
            seen.add(ip)
            out.append(ip)
    return out


def collect(insts: list, domains: list | None = None) -> dict:
    """并发查询：全部服务器 × 全部域 → 扁平 entries（带源名，聚合归 collect.py）。

    并发**统一用治理层 `probe.race`**（守护线程 + deadline 到点收手 + 异常不外抛），
    与 hub / collect / speedtest 同一套语义：到点即返回，**不阻塞进程退出**。
    （历史实现用 ThreadPoolExecutor：其 worker 非守护，Python 退出时会 join，
      导致 hub 的 deadline 形同虚设、进程退不出去——已归一。）
    返回 {ok, entries:[{ip, domain, source}], tried:[…]}。
    """
    servers = insts
    doms = domains or []
    t0 = time.perf_counter()
    entries: list = []
    tried = []
    if servers and doms:
        tasks = [("%s|%s" % (s["name"], d), (lambda s=s, d=d: _query(s, d)))
                 for s in servers for d in doms]
        done = 0
        for key, ok, ips, _ms in _probe.race(tasks, workers=WORKERS_DOMAIN,
                                            deadline=TIMEOUT * 3):
            if not ok:
                continue                       # 该 (服务器,域) 组合超时/失败：跳过，不阻塞其余
            done += 1
            sname, d = key.split("|", 1)
            for ip in ips or []:
                entries.append({"ip": ip, "domain": d, "source": "doh/" + sname})
        for s in servers:
            n = sum(1 for e in entries if e["source"] == "doh/" + s["name"])
            tried.append({"source": "doh/" + s["name"], "ok": n > 0, "count": n,
                          "detail": "解析 %d 条/作业 %d" % (n, done)})
    return {"ok": bool(entries), "entries": entries,
            "tried": tried, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    node = json.loads((_PKG / "sources" / "sources.json").read_text(encoding="utf-8"))["kinds"]["ip"]
    insts = [s for s in ((node["ways"][WAY] or {}).get("sources") or []) if s.get("enabled", True)]
    print(json.dumps(collect(insts, node.get("domains")), ensure_ascii=False, indent=2))
