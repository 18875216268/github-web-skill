#!/usr/bin/env python3
"""hosts 通道单测：授权门 / 标记块幂等 / 备份 / 回滚（全程用假 hosts 文件，不碰系统）。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp(prefix="gh_hosts_test_"))
os.environ["GH_ACCESS_HOME"] = str(tmp / "home")     # 用户区也隔离，避免污染真实日志/备份
os.environ["GH_HOSTS_FILE"] = str(tmp / "hosts")     # 假 hosts

sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TESTS.parent / "scripts"))

import channel_hosts  # noqa: E402
from _harness import check, finish  # noqa: E402

ORIGINAL = "127.0.0.1 localhost\n# 用户自己的内容\n"
POOL = {"raw.githubusercontent.com": ["185.199.108.133"], "github.com": ["140.82.113.3"]}


def main() -> int:
    hosts_file = Path(os.environ["GH_HOSTS_FILE"])
    hosts_file.write_text(ORIGINAL, encoding="utf-8")

    st = channel_hosts.status()
    check("初始状态：未安装且可写", st["installed"] is False and st["writable"] is True, st)

    r = channel_hosts.apply(POOL, confirmed=False)
    check("未授权 apply → need_confirm（不落盘）",
          r.get("need_confirm") is True and channel_hosts.MARK_START not in hosts_file.read_text(encoding="utf-8"))

    r1 = channel_hosts.apply(POOL, confirmed=True)
    text1 = hosts_file.read_text(encoding="utf-8")
    check("授权 apply 成功", r1.get("ok") is True, r1)
    check("标记块已写入且域名齐全",
          channel_hosts.MARK_START in text1 and "raw.githubusercontent.com" in text1 and "github.com" in text1)
    check("原内容未被破坏", "# 用户自己的内容" in text1 and "127.0.0.1 localhost" in text1)
    check("已留备份", Path(r1["backup"]).exists())
    check("幂等：重复 apply 只保留一个标记块",
          channel_hosts.apply(POOL, confirmed=True).get("ok") is True
          and hosts_file.read_text(encoding="utf-8").count(channel_hosts.MARK_START) == 1)

    r2 = channel_hosts.rollback()
    check("回滚成功", r2.get("ok") is True, r2)
    check("回滚后与原文一致", hosts_file.read_text(encoding="utf-8") == ORIGINAL,
          hosts_file.read_text(encoding="utf-8")[:80])

    # 无备份时剥离标记块
    for bak in (Path(os.environ["GH_ACCESS_HOME"]) / "backup").glob("hosts.*.bak"):
        bak.unlink()
    channel_hosts.apply(POOL, confirmed=True)
    r3 = channel_hosts.rollback()
    text3 = hosts_file.read_text(encoding="utf-8")
    check("无备份时剥离标记块", r3.get("ok") is True and channel_hosts.MARK_START not in text3)
    check("剥离后保留用户原内容", "# 用户自己的内容" in text3)

    return finish("test_hosts_marker")


if __name__ == "__main__":
    raise SystemExit(main())
