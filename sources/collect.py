"""资源层大类聚合器（D14/D16 统一形态）：双模式数据驱动。

模式分派（按 sources.json 的 kinds 节形态，新增大类零代码）：
  有 "ways"      → _fetch_driven：并发加载 fetch 脚本（路径=数据）→ 聚合去重
                   （fetch 协议约定：返回 {entries:[{ip,domain,source}], tried} ；
                     产出含 "cidrs" 的方式 = 官方段旁路 meta，不进候选）
  只有 "sources" → _register：纯登记（enabled 过滤 + 字段透传）
  两者并存       → 登记与动态合并（如 mirror 未来引入 dynamic 获取时零改码启用）
输出统一：{"ok","candidates","tried","meta","elapsed"}——hub 测速管道的直接输入。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import probe as _probe  # noqa: E402

_DEADLINE = 20.0


def _load_fetch(rel: str):
    """按 sources.json 声明的相对路径加载 fetch 模块（路径=数据，增方式零改码）。"""
    spec = importlib.util.spec_from_file_location(
        "sources_fetch_" + rel.replace("/", "_").replace(".py", ""), _HERE / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _register(kind: str, node: dict) -> dict:
    """纯登记模式：enabled 过滤 + 字段透传（未知字段保留——字段演进不破坏消费方）。"""
    candidates: list = []
    n_all = 0
    for it in node.get("sources") or []:
        n_all += 1
        if not it.get("enabled", True) or not it.get("url"):
            continue
        candidates.append(dict(it, kind=kind))
    return {"candidates": candidates,
            "tried": [{"source": "%s.sources" % kind, "ok": bool(candidates),
                       "count": len(candidates), "detail": "登记 %d/%d 源" % (len(candidates), n_all)}]}


def _fetch_driven(kind: str, node: dict, domains: list | None) -> dict:
    """fetch 驱动模式：并发跑全部获取方式 → 聚合去重（同域交叉印证 sources[]）。"""
    t0 = time.perf_counter()
    ways = node.get("ways") or {}
    mods = {}
    for name, way in ways.items():
        rel = (way or {}).get("fetch")
        if rel:
            mods[name] = _load_fetch(rel)

    tasks = []
    for name, mod in mods.items():
        insts = (ways.get(name) or {}).get("sources") or []
        tasks.append((name, (lambda m=mod, i=insts: m.collect(i, domains))))
    entries: list = []
    tried: list = []
    meta: dict = {}
    for key, ok, val, _ms in _probe.race(tasks, workers=len(tasks) or 1, deadline=_DEADLINE):
        v = val or {}
        tried += v.get("tried") or []
        if "cidrs" in v:                      # 官方段旁路（如 gh_meta）：安全闸数据，非候选
            meta["cidrs"] = v.get("cidrs") or []
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
    candidates = [dict(c, kind=kind) for c in
                  sorted(agg.values(), key=lambda x: (x["domain"], x["ip"]))]
    return {"candidates": candidates, "tried": tried, "meta": meta,
            "elapsed": round(time.perf_counter() - t0, 2)}


def collect_kind(kind: str, node: dict, domains: list | None = None) -> dict:
    """单大类聚合（模式分派）：hub 的直接调用面。"""
    t0 = time.perf_counter()
    candidates: list = []
    tried: list = []
    meta: dict = {}
    if node.get("ways"):
        r = _fetch_driven(kind, node, domains)
        candidates += r["candidates"]
        tried += r["tried"]
        meta.update(r["meta"])
    if node.get("sources"):
        r = _register(kind, node)
        candidates += r["candidates"]
        tried += r["tried"]
    return {"ok": bool(candidates), "candidates": candidates, "tried": tried,
            "meta": meta, "elapsed": round(time.perf_counter() - t0, 2)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    kinds = json.loads((_HERE / "sources.json").read_text(encoding="utf-8"))["kinds"]
    out = {}
    for k, node in kinds.items():
        r = collect_kind(k, node, (node or {}).get("domains"))
        out[k] = {"ok": r["ok"], "candidates": len(r["candidates"]),
                  "meta": {m: len(v) if isinstance(v, list) else v for m, v in r["meta"].items()},
                  "elapsed": r["elapsed"]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
