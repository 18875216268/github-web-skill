"""获取方式①：hosts 清单源——HTTP 拉 hosts 文本 → 解析 → 候选映射。

统一纪律（D15）：实例清单由 collect 注入（来自 sources.json 的 ways.hosts_file.sources）→
全部并发拉取 → 单源失败跳过（tried 留痕）→ 聚合去重 → 交大类聚合器（collect.py）。
解析容错：注释/# 行跳过、坏行忽略、`alive.` 前缀归一化、重复条目去重。
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

WAY = "hosts_file"
HOSTS_LINE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})\s+(\S+)$")
WORKERS = 8
TIMEOUT = 10.0


def _pull(inst: dict) -> tuple:
    """拉单个清单源 → (name, {domain:[ip]} | {}, detail)。"""
    args = env_guard.curl_base(TIMEOUT) + ["-fsSL", inst["url"]]
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env_guard.clean_env(), timeout=TIMEOUT + 4)
    except Exception as exc:
        return inst["name"], {}, "拉取失败：%s" % str(exc)[:80]
    if p.returncode != 0 or not (p.stdout or "").strip():
        return inst["name"], {}, "HTTP 失败（rc=%s）" % p.returncode
    got: dict = {}
    for ln in p.stdout.splitlines():
        m = HOSTS_LINE.match(ln.strip())
        if not m:
            continue                                  # 注释/坏行忽略
        ip, dom = m.group(1), m.group(2)
        if dom.startswith("alive."):
            dom = dom[len("alive."):]
        bucket = got.setdefault(dom, [])
        if ip not in bucket:
            bucket.append(ip)
    return inst["name"], got, "ok（%d 域）" % len(got)


def _one(inst: dict) -> dict:
    """把 `_pull` 的三元组包装成 race 认识的 dict（race 约定：有 "ok" 键即成败）。"""
    name, got, detail = _pull(inst)
    return {"ok": bool(got), "got": got, "detail": detail}


def collect(insts: list, domains: list | None = None) -> dict:
    """并发拉取全部启用实例 → 扁平 entries（带源名，聚合归 collect.py）。

    并发**统一用治理层 `probe.race`**（守护线程 + deadline 到点收手 + 异常不外抛），
    与 hub / collect / speedtest 同一套语义：到点即返回，**不阻塞进程退出**。
    （历史实现用 ThreadPoolExecutor：其 worker 非守护，Python 退出时会 join，
      导致 deadline 形同虚设、进程退不出去——已归一。）
    返回 {ok, entries:[{ip, domain, source}], tried:[…]}。
    """
    t0 = time.perf_counter()
    entries: list = []
    tried = []
    if insts:
        tasks = [(s["name"], (lambda s=s: _one(s))) for s in insts]
        for name, ok, val, _ms in _probe.race(tasks, workers=WORKERS, deadline=TIMEOUT + 8):
            v = val or {}
            got = v.get("got") or {}
            n = 0
            for dom, ips in got.items():
                for ip in ips:
                    entries.append({"ip": ip, "domain": dom, "source": name})
                    n += 1
            tried.append({"source": name, "ok": bool(ok) and bool(got), "count": n,
                          "detail": v.get("detail", "")})
    return {"ok": bool(entries), "entries": entries,
            "tried": tried, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    node = json.loads((_PKG / "sources" / "sources.json").read_text(encoding="utf-8"))["kinds"]["ip"]
    insts = [s for s in ((node["ways"][WAY] or {}).get("sources") or []) if s.get("enabled", True)]
    print(json.dumps(collect(insts), ensure_ascii=False, indent=2))
