#!/usr/bin/env python3
"""并发探测与源健康账本自检（离线，不出网）。

验证两条用户原则：
  ① **失败 ≠ 失效**：源只冷却、永不删除；冷却到期自动半开重试。
  ② **并发择优**：同时探测各源，完成即用（最快者先返回），到 deadline 收手换方式。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
SCRIPTS = PKG / "scripts"
HOME = Path(tempfile.mkdtemp(prefix="gh_probe_home_"))
os.environ["GH_ACCESS_HOME"] = str(HOME)         # 隔离用户区（账本写这里）

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True

from _harness import check, finish        # noqa: E402
import json                               # noqa: E402
import lines                              # noqa: E402
import probe                              # noqa: E402
import channel_cdn                        # noqa: E402
import channel_mirror                     # noqa: E402
import channel_pin                        # noqa: E402

ip_domains = json.loads((TESTS.parent / "sources" / "ip" / "domains.json").read_text(encoding="utf-8"))["domains"]

WELL_KNOWN_HTTP = ["gh-proxy.com", "ghfast.top", "ghproxy.net", "ghproxy.homeboyc.cn",
                   "github.akams.cn", "hub.gitmirror.com", "github.moeyy.xyz"]
WELL_KNOWN_GIT = ["gitclone.com", "kkgithub.com"]
WELL_KNOWN_CDN = ["jsdelivr", "jsdelivr-fastly", "statically", "githack"]


def main() -> int:
    # ---------- 源池完整性（收录原则：社区公认 + 只增不删；源池在各方式目录） ----------
    http = [s["name"] for s in channel_mirror.SOURCES if "http" in s["caps"]]
    git = [s["name"] for s in channel_mirror.SOURCES if "git" in s["caps"]]
    cdn = [c["name"] for c in channel_cdn.SOURCES]
    check("P1 镜像池含全部社区公认源（含当前可能不可达者，不得删除）",
          all(n in http for n in WELL_KNOWN_HTTP) and all(n in git for n in WELL_KNOWN_GIT),
          "http=%d git=%d" % (len(http), len(git)))
    check("P2 CDN 池含 jsDelivr 多边缘 + 公认等价源（statically/githack）",
          all(n in cdn for n in WELL_KNOWN_CDN), cdn)
    check("P3 每条源都有 name/url/caps/note 且名字唯一",
          len({s["name"] for s in channel_mirror.SOURCES}) == len(channel_mirror.SOURCES)
          and len({c["name"] for c in channel_cdn.SOURCES}) == len(channel_cdn.SOURCES)
          and all(s.get("url") and s.get("caps") and s.get("note") for s in channel_mirror.SOURCES)
          and all(c.get("url") and c.get("note") for c in channel_cdn.SOURCES), None)
    pin_src = (TESTS.parent / "channels" / "pin" / "channel_pin.py").read_text(encoding="utf-8")
    check("P4 pin = 纯应用通道（零获取逻辑：调资源层 hub，无本地探测/池）",
          "hub.collect" in pin_src.replace(" ", "") or "_hub.collect()" in pin_src
          and "_fetch_ipscan" not in pin_src and "POOLS" not in pin_src, None)
    check("P4b 宽域清单来自资源层 domains.json 且覆盖核心 GitHub 域",
          all(d in ip_domains for d in ("github.com", "raw.githubusercontent.com",
                                        "api.github.com", "codeload.github.com", "github.io")),
          len(ip_domains))

    # ---------- 账本：失败只冷却、永不删除 ----------
    key = "gh-proxy.com"
    probe.record(key, True, 120.0, "test ok")
    check("P5 成功：连败清零、无冷却、进热源",
          probe.cooldown_left(key) == 0 and key in probe.recent_ok([key])
          and probe.state(key)["ok_count"] >= 1, probe.state(key))
    for _ in range(3):
        probe.record(key, False, 0.0, "test fail")
    st = probe.state(key)
    check("P6 连败 3 次：指数冷却（60→120→240s 量级）",
          200 < probe.cooldown_left(key) <= lines.PROBE["cooldown_max"] + 1 and st["fail_streak"] == 3, st)
    ordered = probe.order([key, "ghfast.top", "never-seen"])
    check("P7 冷却中的源仍在候选序列内（失败 ≠ 失效：只排后、不删除）",
          set(ordered) == {key, "ghfast.top", "never-seen"} and ordered[-1] == key, ordered)
    check("P8 未知源排在冷却源之前（新源永远有机会被试）",
          ordered.index("never-seen") < ordered.index(key), ordered)

    for _ in range(12):
        probe.record("ghps", False)
    check("P9 冷却封顶（≤ cooldown_max；到期自动半开重试）",
          probe.cooldown_left("ghps") <= lines.PROBE["cooldown_max"] + 1, probe.cooldown_left("ghps"))

    # ---------- 并发择优：完成即用 ----------
    def slow():
        time.sleep(0.30)
        return {"ok": True}

    def fast():
        time.sleep(0.05)
        return {"ok": True}

    def dead():
        time.sleep(0.02)
        return {"ok": False, "detail": "boom"}

    t0 = time.perf_counter()
    res = probe.race([("slow", slow), ("fast", fast), ("dead", dead)], workers=3, deadline=5.0)
    dt = time.perf_counter() - t0
    check("P10 并发探测：完成即用（快的先返回，不等慢的）",
          [k for k, ok, _v, _m in res if ok] == ["fast", "slow"], res)
    check("P11 并发壁钟 ≈ 最慢者而非串行之合（%.2fs < 0.9s）" % dt, dt < 0.9, dt)
    check("P12 失败/异常不打崩，如实返回",
          any(k == "dead" and ok is False for k, ok, _v, _m in res), res)

    t0 = time.perf_counter()
    probe.race([("a", slow), ("b", slow), ("c", slow)], workers=2, deadline=0.25)
    dt = time.perf_counter() - t0
    check("P13 到 deadline 即收手（不无限等）", dt < 1.2, dt)

    # ---------- 惰性快路径：热源零探测开销，只有热源失败才付探测成本 ----------
    probe.record("A", True, 10.0, "hot")
    calls = []
    it = probe.candidates(["A", "B", "C"],
                          probe_fn=lambda n: (calls.append(n), {"ok": True})[1])
    first = next(it)
    check("P15 热源第一个产出，且此时不触发任何探测（零开销快路径）",
          first == "A" and calls == [], (first, calls))
    rest_names = list(it)
    check("P16 热源耗尽后才并发探活（慢路径才付探测成本）",
          bool(calls) and set(rest_names) <= {"B", "C"}, (calls, rest_names))

    # ---------- plan：热源 → 探活胜者 → 其余（不遗漏候选池） ----------
    names = ["gh-proxy.com", "ghfast.top", "gh-static", "ghps", "moeyy"]
    plan = probe.plan(names, probe_fn=lambda n: {"ok": n == "gh-static"})
    check("P14 plan 含探活胜者且结果只来自候选池（未删除任何源）",
          "gh-static" in plan and set(plan) <= set(names), plan)

    shutil.rmtree(HOME, ignore_errors=True)
    return finish("test_probe")


if __name__ == "__main__":
    raise SystemExit(main())
