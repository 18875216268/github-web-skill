"""通道 cdn：换内容来源——从媒体 CDN 的边缘缓存读**单个文件**。

作用：只读单文件（manifest / README / 小配置）时的首选。
前提与边界：只读；不替代 git；分支引用有缓存滞后，正式判定请用 tag/commit 固定。
择路：账本热源直取 → **并发 HEAD 探活完成即用**（最快者先试）→ 其余按账本序兜底；
     内容级校验（200 + 错误说明的历史）不可省；失败只冷却、永不删除。
"""
from __future__ import annotations

from pathlib import Path

import lines
import probe
from channel_direct import http_get

SRCS = {s["name"]: s for s in lines.CDN_SOURCES}


def build_urls(owner: str, repo: str, ref: str, path: str) -> list:
    return [(c["name"], c["url"].format(owner=owner, repo=repo, ref=ref, path=path))
            for c in lines.CDN_SOURCES]


def fetch(owner: str, repo: str, ref: str, path: str, dest: Path, timeout: float) -> dict:
    urls = build_urls(owner, repo, ref, path)
    names = [n for n, _ in urls]
    u = dict(urls)
    tried = []
    for name in probe.candidates(names, probe_pairs=list(urls)):
        r = http_get(u[name], dest, timeout)
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
            return {"ok": True, "channel": "cdn", "via": name, "third_party": "media-cdn",
                    "elapsed": r["elapsed"], "detail": "%s <- %s" % (path, u[name]), "tried": tried}
    return {"ok": False, "channel": "cdn", "third_party": "media-cdn",
            "elapsed": sum(x.get("elapsed", 0) for x in tried) or 0.0,
            "detail": "全部 CDN 域失败", "tried": tried}
