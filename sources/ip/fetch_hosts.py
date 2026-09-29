"""获取方式①：hosts 清单源——HTTP 拉 hosts 文本 → 解析 → 候选映射。

统一纪律（D15）：实例清单由 collect 注入（来自 sources.json 的 ways.hosts_file.sources）→
全部并发拉取 → 单源失败跳过（tried 留痕）→ 聚合去重 → 交大类聚合器（collect.py）。
解析容错：注释/# 行跳过、坏行忽略、`alive.` 前缀归一化、重复条目去重。
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
_PKG = _HERE.parents[1]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402

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


def collect(insts: list, domains: list | None = None) -> dict:
    """并发拉取全部启用实例 → 扁平 entries（带源名，聚合归 collect.py）。

    返回 {ok, entries:[{ip, domain, source}], tried:[…]}。
    """
    t0 = time.perf_counter()
    entries: list = []
    tried = []
    if insts:
        with _cf.ThreadPoolExecutor(max_workers=min(WORKERS, len(insts))) as ex:
            futs = {ex.submit(_pull, d): d for d in insts}
            try:
                pending = _cf.as_completed(futs, timeout=TIMEOUT + 8)
                for f in pending:
                    name, got, detail = f.result()
                    n = 0
                    for dom, ips in got.items():
                        for ip in ips:
                            entries.append({"ip": ip, "domain": dom, "source": name})
                            n += 1
                    tried.append({"source": name, "ok": bool(got), "count": n, "detail": detail})
            except _cf.TimeoutError:
                pass                     # 到点收口：保留已收 entries（D12/D15 纪律——不丢部分结果）
    return {"ok": bool(entries), "entries": entries,
            "tried": tried, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    node = json.loads((_PKG / "sources" / "sources.json").read_text(encoding="utf-8"))["kinds"]["ip"]
    print(json.dumps(collect((node["ways"][WAY] or {}).get("sources") or []), ensure_ascii=False, indent=2))
