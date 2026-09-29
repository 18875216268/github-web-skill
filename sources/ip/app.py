"""IP 大类聚合器（D14）：方式间并发 → 失败跳过（tried 留痕）→ 同域去重 + 交叉印证。

输出扁平候选列表（= speedtest 直接输入，零转换）。**不做域过滤**（D21：hub 全量供给，
消费方零过滤）——全部候选交出，由消费方按需应用。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parents[1]
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import probe as _probe  # noqa: E402

_WAYS = [("hosts_file", _HERE / "hosts_file" / "fetch.py"),
         ("doh", _HERE / "doh" / "fetch.py"),
         ("gh_meta", _HERE / "gh_meta" / "fetch.py")]
_DEADLINE = 20.0


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location("sources_ip_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def collect() -> dict:
    """并发跑全部获取方式 → 聚合去重（交叉印证 sources[]）。

    返回 {"ok", "candidates":[{ip, domain, sources[]}], "tried":[…], "meta":{"cidrs":[…]}}。
    gh_meta 特殊：产出官方段（安全闸数据），原样附带给 hub 过滤，不混入 IP 候选。
    """
    t0 = time.perf_counter()
    mods = {name: _load(name, p) for name, p in _WAYS if p.is_file()}

    tasks = []
    for name, mod in mods.items():
        tasks.append((name, (lambda m=mod: m.collect())))
    res = _probe.race(tasks, workers=len(tasks) or 1, deadline=_DEADLINE)

    entries: list = []
    tried: list = []
    meta = {}
    for key, ok, val, _ms in res:
        v = val or {}
        tried += v.get("tried") or []
        if key == "gh_meta":
            meta = {"cidrs": v.get("cidrs") or []}
            continue
        if ok:
            entries += v.get("entries") or []

    # 聚合去重 + 交叉印证：(ip, domain) 唯一；sources[] 收集全部提供者
    agg: dict = {}
    for e in entries:
        k = (e["ip"], e["domain"])
        if k not in agg:
            agg[k] = {"ip": e["ip"], "domain": e["domain"], "sources": []}
        if e["source"] not in agg[k]["sources"]:
            agg[k]["sources"].append(e["source"])
    candidates = sorted(agg.values(), key=lambda x: (x["domain"], x["ip"]))
    return {"ok": bool(candidates), "candidates": candidates, "tried": tried,
            "meta": meta, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
