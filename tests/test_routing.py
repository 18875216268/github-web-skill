#!/usr/bin/env python3
"""路由表单测：链有效 / 无环 / 写操作禁 mirror / 文档与事实源一致。"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "scripts"))

import gh  # noqa: E402
from _harness import check, finish  # noqa: E402


def main() -> int:
    routes = gh.load_routes()
    names = set(routes["channels"])

    for s in routes["scenarios"]:
        chain = gh.chain_for(s["id"], routes)
        check("场景 %s：链非空且通道均存在" % s["id"],
              bool(chain) and all(c in names for c in chain), chain)
        check("场景 %s：链无重复节点" % s["id"], len(set(chain)) == len(chain), chain)

    check("红线：git_write 链中无 mirror", "mirror" not in gh.chain_for("git_write", routes))
    check("file_read 走 cdn 优先", gh.chain_for("file_read", routes)[0] == "cdn")
    check("git_read 走 direct 优先", gh.chain_for("git_read", routes)[0] == "direct")
    try:
        gh.chain_for("no_such_scenario", routes)
        check("未知场景应报错", False)
    except KeyError:
        check("未知场景应报错", True)

    md = (Path(__file__).resolve().parents[1] / "routes" / "ROUTES.md")
    check("ROUTES.md 已生成", md.exists())
    check("ROUTES.md 与 routes.json 一致（无漂移）",
          md.exists() and md.read_text(encoding="utf-8") == gh.render_routes(routes))
    check("渲染内容包含红线段", "## 红线" in gh.render_routes(routes))

    return finish("test_routing")


if __name__ == "__main__":
    raise SystemExit(main())
