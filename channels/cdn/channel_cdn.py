"""通道 cdn：换内容来源——从媒体 CDN 的边缘缓存读**单个文件**。

作用：只读单文件（manifest / README / 小配置）时的首选。
前提与边界：只读；不替代 git；分支引用有缓存滞后，正式判定请用 tag/commit 固定。
择路：账本热源直取 → **并发 HEAD 探活完成即用**（最快者先试）→ 其余按账本序兜底；
     内容级校验（200 + 错误说明的历史）不可省；失败只冷却、永不删除。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import probe
from channel_direct import http_get as _curl_get

# 源池：统一资源层（sources.json 的 kinds.cdn 节——源与消费分离，D16/D22）
SOURCES = json.loads((Path(__file__).resolve().parents[2] / "sources" / "sources.json")
                     .read_text(encoding="utf-8"))["kinds"]["cdn"]["sources"]
SRCS = {s["name"]: s for s in SOURCES}


def build_urls(owner: str, repo: str, ref: str, path: str) -> list:
    return [(c["name"], c["url"].format(owner=owner, repo=repo, ref=ref, path=path))
            for c in SOURCES]


def fetch(owner: str, repo: str, ref: str, path: str, dest: Path, timeout: float,
          budget=None) -> dict:
    urls = build_urls(owner, repo, ref, path)
    names = [n for n, _ in urls]
    u = dict(urls)
    tried = []
    for name in probe.candidates(names, probe_pairs=list(urls)):
        if budget is not None and not budget.can_attempt():
            tried.append({"cdn": name, "ok": False, "detail": "预算不足，停止 CDN 降级"})
            break
        r = _curl_get(u[name], dest, timeout)
        probe.record(name, bool(r["ok"]), float(r.get("elapsed", 0.0)) * 1000, r.get("detail", ""))
        tried.append({"cdn": name, "ok": r["ok"], "detail": r.get("detail")})
        if r["ok"]:
            # 内容级校验：CDN 有"200 + 错误说明文本"的历史，不能只看状态码
            from channel_direct import content_sane
            sane, why = content_sane(dest, path)
            if not sane:
                probe.record(name, False, 0.0, "内容校验不过：%s" % why)
                tried[-1].update({"ok": False, "detail": "CDN 内容校验不过：%s" % why})
                continue
            if budget is not None:
                budget.register_ok()
            return {"ok": True, "channel": "cdn", "via": name, "third_party": "media-cdn",
                    "elapsed": r["elapsed"], "detail": "%s <- %s" % (path, u[name]), "tried": tried}
    return {"ok": False, "channel": "cdn", "third_party": "media-cdn",
            "elapsed": sum(x.get("elapsed", 0) for x in tried) or 0.0,
            "detail": "全部 CDN 域失败", "tried": tried}


_RAW_RE = re.compile(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/([^/]+)/(.+)")


def http_get(raw_url: str, dest: Path, timeout: float, budget=None) -> dict:
    """统一入口（注册表分发用）：仅支持 raw 形式链接——解析出 owner/repo/ref/path 后走 fetch。

    非 raw 链接（Release 资产 / codeload 等）CDN 天然不适用：如实报不适用（上层会继续降级）。
    """
    m = _RAW_RE.match(raw_url or "")
    if not m:
        return {"ok": False, "channel": "cdn", "third_party": "media-cdn", "elapsed": 0.0,
                "detail": "CDN 仅适用 raw 形式的单文件（当前链接非 raw）"}
    return fetch(m.group(1), m.group(2), m.group(3), m.group(4), dest, timeout, budget=budget)


def git_run(args: list, cwd: str | None, timeout: float, budget=None) -> dict:
    """统一接口占位：cdn 无 git 能力（源池只做 HTTP 只读），如实报不支持。"""
    return {"ok": False, "channel": "cdn", "third_party": "media-cdn", "rc": 1,
            "out": "", "err": "", "elapsed": 0.0,
            "detail": "cdn 不支持 git 操作（内容来源通道，无 git 能力）"}
