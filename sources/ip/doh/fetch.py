"""获取方式②：DoH 解析源——DNS 协议查询（异构于 hosts 清单拉取）→ 候选映射。

统一纪律（D15）：glob 发现本文件夹实例（DoH 服务器）→ 并发查询 →
单服务器失败跳过（tried 留痕）→ 双服务器结果**合并去重**（候选宁多勿漏，测速会筛）。
查询目标域 = `../domains.json`（大类级共享全量域清单）。
"""
from __future__ import annotations

import concurrent.futures as _cf
import json
import re
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_IP_DIR = _HERE.parent
_PKG = _HERE.parents[2]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402

IP_RE = re.compile(r'"data":"(\d+\.\d+\.\d+\.\d+)"')
TIMEOUT = 6.0
WORKERS_DOMAIN = 16


def instances() -> list:
    out = []
    for p in sorted(_HERE.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("enabled", True) and d.get("url"):
            out.append(d)
    return out


def domains() -> list:
    """全量域清单（大类共享配置）。"""
    try:
        return json.loads((_IP_DIR / "domains.json").read_text(encoding="utf-8")).get("domains") or []
    except Exception:
        return []


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


def collect() -> dict:
    """并发查询：全部服务器 × 全部域 → 扁平 entries（带源名，聚合归 app.py）。

    返回 {ok, entries:[{ip, domain, source}], tried:[…]}。
    """
    servers = instances()
    doms = domains()
    t0 = time.perf_counter()
    entries: list = []
    tried = []
    if servers and doms:
        jobs = [(s, d) for s in servers for d in doms]

        def one(job):
            s, d = job
            return s["name"], d, _query(s, d)

        done = 0
        with _cf.ThreadPoolExecutor(max_workers=min(WORKERS_DOMAIN, len(jobs))) as ex:
            futs = {ex.submit(one, j): j for j in jobs}
            try:
                pending = _cf.as_completed(futs, timeout=TIMEOUT * 3)
                for f in pending:
                    sname, d, ips = f.result()
                    done += 1
                    for ip in ips:
                        entries.append({"ip": ip, "domain": d, "source": "doh/" + sname})
            except _cf.TimeoutError:
                pass                     # 到点收口：保留已收 entries（D12/D15 纪律）
        for s in servers:
            n = sum(1 for e in entries if e["source"] == "doh/" + s["name"])
            tried.append({"source": "doh/" + s["name"], "ok": n > 0, "count": n,
                          "detail": "解析 %d 条/作业 %d" % (n, done)})
    return {"ok": bool(entries), "entries": entries,
            "tried": tried, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
