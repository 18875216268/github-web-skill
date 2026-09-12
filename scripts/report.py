"""报告与日志：JSON 给 Agent，人读摘要给日志（默认 stderr），全量留痕在用户区。

约定：
  stdout = 单个 JSON（Agent 直接解析）；
  stderr = 一行人类摘要（可选 --quiet 关闭）；
  日志   = 用户区 ~/.github-access/logs/gh-YYYYMM.jsonl（永不写回包内）。
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("GH_ACCESS_HOME") or (Path.home() / ".github-access"))


def ensure_home() -> Path:
    (HOME / "logs").mkdir(parents=True, exist_ok=True)
    (HOME / "cache").mkdir(parents=True, exist_ok=True)
    (HOME / "backup").mkdir(parents=True, exist_ok=True)
    return HOME


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(event: str, **fields) -> None:
    """JSONL 留痕（失败不影响主流程）。"""
    try:
        ensure_home()
        f = HOME / "logs" / ("gh-%s.jsonl" % datetime.datetime.now().strftime("%Y%m"))
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now(), "event": event, **fields}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def emit(result: dict, quiet: bool = False) -> None:
    """stdout 输出 JSON；stderr 输出一行人类摘要。"""
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not quiet:
        print(human_summary(result), file=sys.stderr)


def human_summary(result: dict) -> str:
    head = "OK" if result.get("ok") else "FAIL"
    parts = ["[%s] %s" % (head, result.get("action", "?"))]
    if result.get("channel"):
        parts.append("通道=%s" % result["channel"])
    if result.get("elapsed") is not None:
        parts.append("耗时=%.1fs" % result["elapsed"])
    if result.get("third_party"):
        parts.append("经第三方=%s" % result["third_party"])
    if result.get("detail"):
        parts.append(str(result["detail"])[:120])
    if result.get("next"):
        parts.append("下一步=%s" % result["next"])
    return " ｜ ".join(parts)
