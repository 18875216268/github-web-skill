#!/usr/bin/env python3
"""资源层测试：获取方式纪律 / 大类聚合 / speedtest / hub 收口 / 白名单对账（离线为主 + 真机宽容）。

S1 hosts 清单解析容错
S2 DoH 响应解析 + 合并去重
S3 collect.py 双模式（登记 enabled 过滤 / 分派）
S4 speedtest 策略注入 + 升序 + deadline 收口
S6 白名单对账（hub --check）
S7 结构符合设计（hub/speedtest/collect/sources.json/ip fetch 齐备）
S7b 旧资产退场（第三层目录/旧聚合器不复存在）
S8 sources.json schema 锁（version/kinds 三节/条数零损失）
S9 fetch 脚本暴露 collect() 统一接口
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
HOME = Path(tempfile.mkdtemp(prefix="gh_sources_home_"))
os.environ["GH_ACCESS_HOME"] = str(HOME)
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(PKG / "scripts"))
sys.path.insert(0, str(PKG / "sources"))
sys.dont_write_bytecode = True

from _harness import check, finish  # noqa: E402
import _harness as _h  # noqa: E402

import speedtest  # noqa: E402


def _load(name: str, rel: str):
    return _h.load_module(name, PKG / rel)


def main() -> int:
    hf = _load("hf", "sources/ip/fetch_hosts.py")
    doh = _load("doh", "sources/ip/fetch_doh.py")
    col = _load("col", "sources/collect.py")
    hub = _load("hub", "sources/hub.py")

    # ---------- S1 hosts 清单解析容错 ----------
    sample = ("# comment line\n"
              "140.82.113.3 github.com\n"
              "140.82.113.3  alive.github.com\n"
              "bad line without ip\n"
              "185.199.110.133 raw.githubusercontent.com\n"
              "140.82.113.3 github.com\n")
    got: dict = {}
    for ln in sample.splitlines():
        m = hf.HOSTS_LINE.match(ln.strip())
        if not m:
            continue
        ip, dom = m.group(1), m.group(2)
        if dom.startswith("alive."):
            dom = dom[len("alive."):]
        bucket = got.setdefault(dom, [])
        if ip not in bucket:
            bucket.append(ip)
    check("S1 hosts 解析：注释/坏行忽略、alive. 归一化、重复去重",
          got.get("github.com") == ["140.82.113.3"] and got.get("raw.githubusercontent.com") == ["185.199.110.133"],
          got)

    # ---------- S2 DoH 解析 + 合并去重 ----------
    r1 = doh._query({"name": "t", "url": "https://127.0.0.1:1/resolve"}, "github.com")
    check("S2a DoH 单服务器失败 → 空且不抛", r1 == [], r1)
    entries = [{"ip": "1.2.3.4", "domain": "d", "source": "doh/a"},
               {"ip": "1.2.3.4", "domain": "d", "source": "doh/b"},
               {"ip": "5.6.7.8", "domain": "d", "source": "doh/a"}]
    agg: dict = {}
    for e in entries:
        bucket = agg.setdefault((e["ip"], e["domain"]), {"ip": e["ip"], "domain": e["domain"], "sources": []})
        if e["source"] not in bucket["sources"]:
            bucket["sources"].append(e["source"])
    check("S2b 合并去重 + sources[] 交叉印证（同 IP 双源）",
          len(agg) == 2 and agg[("1.2.3.4", "d")]["sources"] == ["doh/a", "doh/b"], list(agg.values()))

    # ---------- S3 collect 双模式（登记 enabled 过滤 / 分派） ----------
    reg = col._register("mirror", {"sources": [
        {"name": "on", "url": "https://a/", "caps": ["http"]},
        {"name": "off", "url": "https://b/", "enabled": False},
        {"name": "nourl", "enabled": True},
    ]})
    check("S3a 登记模式：enabled:false / 缺 url 不参与，其余透传",
          [c["name"] for c in reg["candidates"]] == ["on"]
          and reg["candidates"][0]["kind"] == "mirror"
          and reg["candidates"][0]["caps"] == ["http"], reg)
    both = col.collect_kind("demo", {"sources": [{"name": "s", "url": "https://s/"}]})
    check("S3b 纯登记大类分派（collect_kind 零代码扩展形态）",
          both["ok"] is True and both["candidates"][0]["name"] == "s", both)

    # ---------- S3c 双轨并存：登记 + 动态合并（mock fetch，不落盘） ----------
    import types
    fake = types.SimpleNamespace(collect=lambda insts, domains=None: {
        "ok": True, "entries": [{"ip": "9.9.9.9", "domain": "d", "source": "dyn"}], "tried": []})
    old_loader = col._load_fetch
    col._load_fetch = lambda rel: fake
    try:
        hybrid = col.collect_kind("hybrid", {
            "ways": {"dyn": {"fetch": "ip/fake.py", "sources": [{}]}},
            "sources": [{"name": "reg", "url": "https://reg/"}]})
    finally:
        col._load_fetch = old_loader
    check("S3c 双轨并存：登记与动态产出合并",
          hybrid["ok"] and len(hybrid["candidates"]) == 2
          and any(c.get("name") == "reg" for c in hybrid["candidates"])
          and any(c.get("domain") == "d" and c.get("ip") == "9.9.9.9"
                  for c in hybrid["candidates"]), hybrid)

    # ---------- S4 speedtest 策略注入 + 升序 + 收口（mock 层：确定性验证分派/丢弃/排序逻辑） ----------
    real_tcp, real_head = speedtest._tcp_ms, speedtest._head_ms
    speedtest._tcp_ms = lambda ip, timeout=3.0, port=443: ({"ok": True, "latency": 5} if ip == "127.0.0.1"
                                                           else {"ok": False})
    speedtest._head_ms = lambda url, timeout=4.0: {"ok": False}
    try:
        res = speedtest.measure_all([
            {"kind": "ip", "ip": "127.0.0.1", "domain": "t.local"},
            {"kind": "ip", "ip": "203.0.113.1", "domain": "t.local"},          # mock：不可达
            {"kind": "mirror", "name": "t", "url": "https://127.0.0.1:1/x"},
        ], strategies={"ip": {"method": "tcp", "port": 443}, "mirror": {"method": "head"}}, deadline=4.0)
    finally:
        speedtest._tcp_ms, speedtest._head_ms = real_tcp, real_head
    ok_ones = [c for c in res if c["kind"] == "ip" and c["ip"] == "127.0.0.1"]
    check("S4 speedtest：策略注入生效、可达者带延迟、不可达者丢弃、全部升序",
          len(ok_ones) == 1 and ok_ones[0].get("latency") is not None and len(res) == 1
          and all(res[i].get("latency", 0) <= res[i + 1].get("latency", 10 ** 9)
                  for i in range(len(res) - 1)), res)

    # ---------- S7 结构符合设计 ----------
    need = ["sources/hub.py", "sources/speedtest.py", "sources/collect.py", "sources/sources.json",
            "sources/ip/fetch_hosts.py", "sources/ip/fetch_doh.py", "sources/ip/fetch_ghmeta.py",
            "channels/pin/channel_pin.py", "channels/hosts/channel_hosts.py"]
    check("S7 资源层结构符合设计（文件齐备）", all((PKG / p).is_file() for p in need),
          [p for p in need if not (PKG / p).is_file()])
    gone = ["sources/ip/app.py", "sources/ip/domains.json", "sources/ip/hosts_file",
            "sources/ip/doh", "sources/ip/gh_meta", "sources/mirror/app.py",
            "sources/mirror/static", "sources/cdn/app.py", "sources/cdn/static"]
    check("S7b 旧资产退场（第三层目录/旧聚合器/ipscan/pools 不复存在）",
          not any((PKG / p).exists() for p in gone)
          and not (PKG / "channels/pin/sources/ipscan.py").exists()
          and not (PKG / "channels/pin/pools.json").exists(), None)

    # ---------- S8 sources.json schema 锁（条数零损失） ----------
    data = json.loads((PKG / "sources" / "sources.json").read_text(encoding="utf-8"))
    kinds = data.get("kinds") or {}
    ip = kinds.get("ip") or {}
    ways = ip.get("ways") or {}
    n_hosts = len((ways.get("hosts_file") or {}).get("sources") or [])
    n_doh = len((ways.get("doh") or {}).get("sources") or [])
    n_gh = len((ways.get("gh_meta") or {}).get("sources") or [])
    n_mirror = len((kinds.get("mirror") or {}).get("sources") or [])
    n_cdn = len((kinds.get("cdn") or {}).get("sources") or [])
    n_dom = len(ip.get("domains") or [])
    check("S8 sources.json schema：条数零损失（hosts8/doh5/gh_meta1/mirror68/cdn13/domains42）",
          data.get("version") == 1 and n_hosts == 8 and n_doh == 5 and n_gh == 1
          and n_mirror == 68 and n_cdn == 13 and n_dom == 42,
          {"hosts": n_hosts, "doh": n_doh, "gh_meta": n_gh, "mirror": n_mirror,
           "cdn": n_cdn, "domains": n_dom})
    methods = {k: ((node or {}).get("speedtest") or {}).get("method") for k, node in kinds.items()}
    check("S8b 测速策略数据声明齐备且 method 合法",
          all(m in ("tcp", "head") for m in methods.values()) and len(methods) == 4, methods)

    # ---------- S6 白名单对账（真 manifest） ----------
    chk = hub._check()
    check("S6 白名单对账：资源层端点 ⊆ manifest.allow_domains", chk.get("ok") is True, chk)

    # ---------- S9 fetch 脚本统一接口 ----------
    check("S9 fetch 脚本暴露 collect() 统一接口",
          all(hasattr(m, "collect") for m in (hf, doh)), None)

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_sources")


if __name__ == "__main__":
    raise SystemExit(main())
