"""通道 hosts：改系统解析（标记块）——仅兜底，必须显式授权且必须可回滚。

纪律（沿用 74rmu1 的成熟设计）：
  只动标记块（# github-web-skill Start/End）；写入前备份到用户区；重复 apply 幂等；
  rollback 优先恢复备份、无备份则剥离标记块；默认不改 DNS 缓存（可用 --flush 显式刷新）。
测试友好：GH_HOSTS_FILE 可指向任意文件（单测/演练用假 hosts，不碰真实系统）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import report

MARK_START = "# github-web-skill Start"
MARK_END = "# github-web-skill End"


def hosts_path() -> Path:
    override = os.environ.get("GH_HOSTS_FILE")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def status() -> dict:
    p = hosts_path()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"ok": False, "installed": False, "path": str(p), "detail": "读取失败：%s" % exc}
    installed = MARK_START in text
    block = ""
    if installed:
        s = text.index(MARK_START)
        e = text.index(MARK_END) + len(MARK_END)
        block = text[s:e]
    return {"ok": True, "installed": installed, "path": str(p), "block": block,
            "writable": os.access(p, os.W_OK)}


def _backup(p: Path) -> Path:
    report.ensure_home()
    dst = report.HOME / "backup" / ("hosts.%s.bak" % __import__("time").strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(p, dst)
    return dst


def render_block(ips_by_domain: dict) -> str:
    lines = [MARK_START, "# 由 github-web-skill 写入：只动本块，删除本块即恢复原状"]
    for domain, ips in ips_by_domain.items():
        for ip in ips:
            lines.append("%-16s %s" % (ip, domain))
    lines.append(MARK_END)
    return "\n".join(lines)


def apply(ips_by_domain: dict, confirmed: bool = False, flush: bool = False) -> dict:
    if not confirmed:
        return {"ok": False, "need_confirm": True, "channel": "hosts",
                "detail": "改系统解析需显式授权：加 --yes 后才执行",
                "next": "gh.py hosts --apply --yes（或由用户批准后重跑）"}
    p = hosts_path()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        # 只在"首次安装"时备份：幂等重跑不得把已打补丁的状态存成备份，
        # 否则 rollback 会恢复到带标记块的版本（单测抓到的真 bug）。
        bak = None if MARK_START in text else _backup(p)
    except Exception as exc:
        return {"ok": False, "channel": "hosts", "detail": "不可写（多为缺管理员权限）：%s" % exc,
                "next": "以管理员身份重跑，或改用 pin 通道（零系统改动）"}
    import re
    text = re.sub(r"(?ms)\r?\n?" + re.escape(MARK_START) + ".*?" + re.escape(MARK_END) + r"\r?\n?", "\n",
                  text)
    new = text.rstrip() + "\n\n" + render_block(ips_by_domain) + "\n"
    try:
        p.write_text(new, encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "channel": "hosts", "detail": "写入失败：%s" % exc}
    if flush and sys.platform == "win32":
        try:
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True)
        except Exception:
            pass
    return {"ok": True, "channel": "hosts", "path": str(p), "backup": str(bak) if bak else None,
            "domains": {d: len(ips) for d, ips in ips_by_domain.items()},
            "detail": "标记块已写入（%d 域）%s；回滚：gh.py hosts --rollback" % (
                len(ips_by_domain), "，备份=%s" % bak.name if bak else "（更新已有块，无需新备份）")}


def rollback() -> dict:
    p = hosts_path()
    baks = sorted((report.HOME / "backup").glob("hosts.*.bak"), reverse=True)
    try:
        if baks:
            shutil.copy2(baks[0], p)
            return {"ok": True, "channel": "hosts", "restored": str(baks[0]),
                    "detail": "已从最近备份恢复（%s）" % baks[0].name}
        text = p.read_text(encoding="utf-8", errors="replace")
        import re
        new = re.sub(r"(?ms)\r?\n?" + re.escape(MARK_START) + ".*?" + re.escape(MARK_END) + r"\r?\n?",
                     "\n", text)
        p.write_text(new, encoding="utf-8")
        return {"ok": True, "channel": "hosts", "detail": "无备份，已剥离标记块"}
    except Exception as exc:
        return {"ok": False, "channel": "hosts", "detail": "回滚失败：%s" % exc}
