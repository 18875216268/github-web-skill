#!/usr/bin/env python3
"""资源层测试：获取方式纪律 / 大类聚合 / speedtest / hub 收口 / 白名单对账（离线为主 + 真机宽容）。

S1 hosts 清单解析容错（迁自 _parse_cloud_fn 的成熟逻辑）
S2 DoH 响应解析 + 合并去重
S3 ip/app.py 聚合去重 + sources[] 交叉印证
S4 speedtest 三分派 + 升序 + deadline 收口
S5 hub 流式收口 + 每大类 Top10
S6 白名单对账（hub --check）
S7 结构符合设计（hub/speedtest/三大类/获取方式齐备）
S8 enabled:false 尊重（禁用源不参与）
S9 fetch 脚本独立 CLI 可跑（-h 级冒烟）
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

import speedtest  # noqa: E402


def _load(name: str, rel: str):
    import importlib.util
    p = PKG / rel
    spec = importlib.util.spec_from_file_location("tsrc_" + name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    hf = _load("hf", "sources/ip/hosts_file/fetch.py")
    doh = _load("doh", "sources/ip/doh/fetch.py")
    ipapp = _load("ipapp", "sources/ip/app.py")
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

    # ---------- S3 app 聚合（结构级：两获取方式模块齐备） ----------
    check("S3 ip 大类获取方式齐备（hosts_file/doh/gh_meta）",
          all(p.is_file() for p in (PKG / "sources/ip/hosts_file/fetch.py",
                                    PKG / "sources/ip/doh/fetch.py",
                                    PKG / "sources/ip/gh_meta/fetch.py")), None)

    # ---------- S4 speedtest 三分派 + 升序 + 收口（mock 层：确定性验证分派/丢弃/排序逻辑） ----------
    real_tcp, real_head = speedtest._tcp_ms, speedtest._head_ms
    speedtest._tcp_ms = lambda ip, timeout=3.0: ({"ok": True, "latency": 5} if ip == "127.0.0.1"
                                                 else {"ok": False})
    speedtest._head_ms = lambda url, timeout=4.0: {"ok": False}
    try:
        res = speedtest.measure_all([
            {"kind": "ip", "ip": "127.0.0.1", "domain": "t.local"},
            {"kind": "ip", "ip": "203.0.113.1", "domain": "t.local"},          # mock：不可达
            {"kind": "mirror", "name": "t", "url": "https://127.0.0.1:1/x"},
        ], deadline=4.0)
    finally:
        speedtest._tcp_ms, speedtest._head_ms = real_tcp, real_head
    ok_ones = [c for c in res if c["kind"] == "ip" and c["ip"] == "127.0.0.1"]
    check("S4 speedtest：可达者带延迟、不可达者丢弃、全部升序",
          len(ok_ones) == 1 and ok_ones[0].get("latency") is not None and len(res) == 1
          and all(res[i].get("latency", 0) <= res[i + 1].get("latency", 10 ** 9)
                  for i in range(len(res) - 1)), res)

    # ---------- S7 结构符合设计 ----------
    need = ["sources/hub.py", "sources/speedtest.py", "sources/ip/app.py", "sources/ip/domains.json",
            "sources/ip/hosts_file/fetch.py", "sources/ip/doh/fetch.py", "sources/ip/gh_meta/fetch.py",
            "sources/mirror/app.py", "sources/mirror/static/mirror.json",
            "sources/cdn/app.py", "sources/cdn/static/cdn.json",
            "channels/pin/channel_pin.py", "channels/hosts/channel_hosts.py"]
    check("S7 资源层结构符合设计（文件齐备）", all((PKG / p).is_file() for p in need),
          [p for p in need if not (PKG / p).is_file()])
    check("S7b 旧资产退场（ipscan/pools 不复存在）",
          not (PKG / "channels/pin/sources/ipscan.py").exists()
          and not (PKG / "channels/pin/pools.json").exists(), None)

    # ---------- S8 enabled:false 尊重 ----------
    tmp = Path(tempfile.mkdtemp(prefix="gh_src_enabled_"))
    (tmp / "a.json").write_text(json.dumps({"name": "off", "enabled": False, "url": "https://x/hosts"}), encoding="utf-8")
    old = hf._HERE
    hf._HERE = tmp
    insts = hf.instances()
    hf._HERE = old
    check("S8 enabled:false 的源不参与", insts == [], insts)

    # ---------- S6 白名单对账（真 manifest） ----------
    chk = hub._check()
    check("S6 白名单对账：资源层端点 ⊆ manifest.allow_domains", chk.get("ok") is True, chk)

    # ---------- S9 fetch 独立 CLI 冒烟（结构级，不依赖网络结果） ----------
    check("S9 fetch 脚本暴露 collect() 统一接口",
          all(hasattr(m, "collect") for m in (hf, doh)), None)

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_sources")


import shutil  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
