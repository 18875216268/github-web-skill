"""获取方式①：hosts 清单源——HTTP 拉 hosts 文本 → 解析 → 候选映射。

统一纪律（D15）：glob 自动发现本文件夹 *.json 实例 → 全部并发拉取 →
单源失败跳过（tried 留痕）→ 聚合去重 → 交大类聚合器（app.py）。
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
_PKG = _HERE.parents[2]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import env_guard  # noqa: E402

HOSTS_LINE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})\s+(\S+)$")
WORKERS = 8
TIMEOUT = 10.0


def instances() -> list:
    """glob 发现全部启用实例（增源=放 json 即生效）。"""
    out = []
    for p in sorted(_HERE.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if d.get("enabled", True) and d.get("url"):
            out.append(d)
    return out


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


def collect() -> dict:
    """并发拉取全部启用实例 → 扁平 entries（带源名，聚合归 app.py）。

    返回 {ok, entries:[{ip, domain, source}], tried:[…]}。
    """
    insts = instances()
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
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
