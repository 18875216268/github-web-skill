"""资源层统一调用（D12）：全局唯一入口——流式三池管道。

① 并发获取池（sources.json 的 kinds 各大类 → collect.py 双模式分派）
② 并发测速池（候选即到即测：策略由 kinds.<类>.speedtest 数据声明——speedtest 统一执行）
③ 可用源清单（按大类各维持 Top10，延迟升序）

收口（全部完成或总预算到点）→ 返回统一 JSON 清单。
定位：通道 import 消费 + 开发/诊断 CLI——agent 不直用资源层（agent 面永远是 gh.py 通道命令）。
"""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
for _p in (str(_PKG / "scripts"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import probe as _probe  # noqa: E402
import speedtest as _speedtest  # noqa: E402

_TOP = 10
_DEADLINE = 25.0
_MANIFEST = _PKG / "manifest.json"
_DATA_F = _HERE / "sources.json"
_DATA = None                                    # 进程内缓存（单次 CLI 生命周期内）


def _data() -> dict:
    global _DATA
    if _DATA is None:
        _DATA = json.loads(_DATA_F.read_text(encoding="utf-8"))
    return _DATA


def _load_collect():
    spec = importlib.util.spec_from_file_location("sources_collect", _HERE / "collect.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _fmt_hosts(ip_list: list) -> str:
    """每域取最快 IP → hosts 行文本（供给全量覆盖）。"""
    best: dict = {}
    for c in ip_list:
        d = c["domain"]
        if d not in best or c["latency"] < best[d]["latency"]:
            best[d] = c
    return "\n".join("%-16s %s" % (c["ip"], c["domain"]) for c in best.values())


def _endpoints() -> list:
    """汇总资源层全部出网端点（域名/IP）——白名单对账数据源。"""
    out: set = set()
    kinds = _data()["kinds"]
    for node in kinds.values():
        for way in (node.get("ways") or {}).values():       # fetch 型：ways.*.sources 的 url
            for s in (way or {}).get("sources") or []:
                u = str(s.get("url") or "")
                if u:
                    out.add(re.sub(r"^https?://", "", u).split("/")[0])
        for s in node.get("sources") or []:                 # 登记型：sources 的 url
            u = str(s.get("url") or "")
            if u:
                out.add(re.sub(r"^https?://", "", u).split("/")[0])
        out |= set(node.get("domains") or [])               # 探测目标域（也是出网对象）
    return sorted(out)


def _check() -> dict:
    """出网自检：资源层端点 ⊆ manifest.allow_domains（只报 missing，单向）。"""
    allow = set()
    try:
        allow = set(json.loads(_MANIFEST.read_text(encoding="utf-8"))
                    ["network"]["allow_domains"])
    except Exception as exc:
        return {"ok": False, "detail": "manifest 读取失败：%s" % exc}
    missing = [e for e in _endpoints() if e not in allow]
    return {"ok": not missing, "checked": len(_endpoints()), "missing_in_allowlist": missing}


def collect(only: tuple | None = None) -> dict:
    """流式三池：并发获取各大类 → 统一测速（策略数据声明）→ 每大类 Top10。

    `only`：只采集指定大类。pin / hosts 只消费 `ip`，不指定就会为 mirror+cdn 白算 81 次测速。
    """
    t0 = time.perf_counter()
    kinds = _data()["kinds"]
    if only:
        kinds = {k: v for k, v in kinds.items() if k in only}
    collect_mod = _load_collect()
    tasks = [(k, (lambda k=k, n=kinds[k]: collect_mod.collect_kind(k, n, n.get("domains"))))
             for k in kinds]
    got = {}
    for key, ok, val, _ms in _probe.race(tasks, workers=len(tasks), deadline=_DEADLINE):
        got[key] = (val or {}) if ok else {"ok": False, "candidates": [], "tried": [
            {"source": key, "ok": False, "detail": "大类获取失败/超时"}]}

    # IP 候选：官方段安全闸（gh_meta 失败/为空 → 跳过过滤）
    ip_cands = got.get("ip", {}).get("candidates") or []
    cidrs = (got.get("ip", {}).get("meta") or {}).get("cidrs") or []
    if cidrs:
        nets = []
        for seg in cidrs:
            try:
                nets.append(ipaddress.ip_network(seg))
            except ValueError:
                continue
        if nets:
            ip_cands = [c for c in ip_cands
                        if any(ipaddress.ip_address(c["ip"]) in n for n in nets)]

    # 候选组装：测速策略数据声明（kinds.<类>.speedtest）——未声明/未知方式 → 不测速，如实留痕
    all_c: list = []
    deferred: dict = {}
    for kind, node in kinds.items():
        strat = node.get("speedtest")
        cands = [dict(c, kind=kind) for c in
                 (ip_cands if kind == "ip" else got.get(kind, {}).get("candidates") or [])]
        if not strat:
            deferred[kind] = (cands, "未声明测速策略，跳过统一测速")
            continue
        if strat.get("method") not in ("tcp", "head"):
            deferred[kind] = (cands, "未知测速方式 %r，跳过统一测速" % strat.get("method"))
            continue
        for c in cands:
            if kind == "cdn":                    # cdn：渲染探针 URL（渲染参数 = 数据）
                u = c["url"]
                try:
                    u = u.format(**(strat.get("args") or {}))
                except Exception:
                    pass
                c["url"] = u
            all_c.append(c)

    ranked = _speedtest.measure_all(all_c, strategies={
        k: kinds[k]["speedtest"] for k in kinds
        if k not in deferred and kinds[k].get("speedtest")}, deadline=_DEADLINE)

    out = {"ok": bool(ranked) or bool(deferred), "elapsed": round(time.perf_counter() - t0, 2)}
    for kind in kinds:
        group = [c for c in ranked if c["kind"] == kind]
        tried = list(got.get(kind, {}).get("tried") or [])
        if kind in deferred:
            tried.append({"source": "speedtest", "ok": False, "detail": deferred[kind][1]})
            group = list(deferred[kind][0])       # 未测速候选原样保留（无 latency，如实标注）
        entry = {"top10": group[:_TOP], "total_candidates": len(group), "tried": tried}
        if kind == "ip":
            by_domain: dict = {}
            for c in group:                       # 每域全部测通候选，延迟升序（pin failover 消费）
                by_domain.setdefault(c["domain"], []).append(c["ip"])
            entry["by_domain"] = by_domain
        out[kind] = entry
    out["meta"] = {"cidrs": len(cidrs), "filtered": bool(cidrs)}
    return out


def main(argv: list) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--check" in argv:
        print(json.dumps(_check(), ensure_ascii=False, indent=2))
        return 0
    if "--endpoints" in argv:
        print(json.dumps({"endpoints": _endpoints()}, ensure_ascii=False, indent=2))
        return 0
    r = collect()
    if "--format" in argv and "hosts" in argv:
        print(_fmt_hosts(r.get("ip", {}).get("top10") or []))
        return 0 if r.get("ok") else 1
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
