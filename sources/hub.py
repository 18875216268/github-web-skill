"""资源层统一调用（D12）：全局唯一入口——流式三池管道。

① 并发获取池（全部源大类同时拉：ip/mirror/cdn 的 app.py）
② 并发测速池（候选即到即测：IP=TCP443，镜像/CDN=HEAD——speedtest 统一分派）
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


def _load(kind: str):
    spec = importlib.util.spec_from_file_location("sources_" + kind + "_app", _HERE / kind / "app.py")
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
    for jf in _HERE.rglob("*.json"):
        if jf.name == "domains.json":
            continue                     # 域清单是探测目标配置，不是端点
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = data.get("sources") if isinstance(data, dict) and "sources" in data else (
            [data] if isinstance(data, dict) and data.get("url") else [])
        for it in items or []:
            u = str(it.get("url") or "")
            host = re.sub(r"^https?://", "", u).split("/")[0]
            if host:
                out.add(host)
    try:
        doms = json.loads((_HERE / "ip" / "domains.json").read_text(encoding="utf-8")).get("domains") or []
        out |= set(doms)
    except Exception:
        pass
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


def collect() -> dict:
    """流式三池（D12）：并发获取三大类 → speedtest 并发测速 → 每大类 Top10。"""
    t0 = time.perf_counter()
    apps = {k: _load(k) for k in ("ip", "mirror", "cdn")}
    tasks = [(k, (lambda m=apps[k]: m.collect())) for k in apps]
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

    # mirror/cdn 候选：cdn 渲染探针 URL（固定轻量文件）供 HEAD 测速
    probe_args = {"owner": "github", "repo": "gitignore", "ref": "main", "path": "README.md"}
    all_c = []
    for c in ip_cands:
        all_c.append(dict(c, kind="ip", url=c["ip"]))
    for c in got.get("mirror", {}).get("candidates") or []:
        all_c.append(dict(c, url=c["url"]))
    for c in got.get("cdn", {}).get("candidates") or []:
        u = c["url"]
        try:
            u = u.format(**probe_args)
        except Exception:
            pass
        all_c.append(dict(c, url=u))

    ranked = _speedtest.measure_all(all_c, deadline=_DEADLINE)
    out = {"ok": bool(ranked), "elapsed": round(time.perf_counter() - t0, 2)}
    for kind in ("ip", "mirror", "cdn"):
        group = [c for c in ranked if c["kind"] == kind]
        tried = got.get(kind, {}).get("tried") or []
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
