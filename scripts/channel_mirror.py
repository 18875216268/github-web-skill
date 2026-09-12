"""通道 mirror：换入口——第三方转发代理池（默认开，只用于只读操作）。

作用：直连与钉 IP 都失败时的只读兜底。
红线：**push / 写操作永不经过本通道**（第三方转发不接触用户写入流量）。
择路：账本热源直取 → **并发探活（HEAD / git ls-remote）完成即用** → 其余按账本序兜底；
     失败只冷却、永不删除（源可能只是暂时不可达，见 lines.MIRROR_SOURCES 收录原则）。
"""
from __future__ import annotations

import re
from pathlib import Path

import lines
import probe

SRCS = {s["name"]: s for s in lines.MIRROR_SOURCES}


def _http_names() -> list:
    return [s["name"] for s in lines.MIRROR_SOURCES if "http" in s["caps"]]


def _git_names() -> list:
    return [s["name"] for s in lines.MIRROR_SOURCES if "git" in s["caps"]]


def _git_args(name: str, args: list) -> list:
    """按源的样式生成 git 重写：默认 `{url}/https://github.com/`；换主机式源用自带 prefix/match。"""
    s = SRCS[name]
    match = s.get("git_match", "https://github.com/")
    prefix = s.get("git_prefix", "%s/https://github.com/" % s["url"])
    return ["-c", "url.%s.insteadOf=%s" % (prefix, match), *args]


def _url(name: str) -> str:
    return SRCS[name]["url"]


def _done(name: str, what: str, r: dict, tried: list) -> dict:
    return {"ok": True, "channel": "mirror", "via": name, "third_party": name,
            "elapsed": r.get("elapsed", 0.0), "detail": "%s <- %s" % (what, _url(name)),
            "tried": tried}


def http_get(raw_url: str, dest: Path, timeout: float, budget=None) -> dict:
    from channel_direct import content_sane, http_get as _curl_get
    names = _http_names()
    tried = []

    def real(name: str) -> dict:
        rt = budget.timeout_for(timeout) if budget is not None else timeout
        r = _curl_get(_url(name) + "/" + raw_url, dest, rt)
        if r["ok"] and not raw_url.startswith(("https://github.com/", "https://codeload.")):
            sane, why = content_sane(dest, raw_url)      # 200 + 壳页/错误页（gh-proxy.net 历史）
            if not sane:
                r = {"ok": False, "detail": why, "elapsed": r.get("elapsed", 0.0)}
        probe.record(name, bool(r["ok"]), float(r.get("elapsed", 0.0)) * 1000, r.get("detail", ""))
        tried.append({"mirror": name, "ok": r["ok"], "detail": r.get("detail")})
        return r

    cand = probe.candidates(names, probe_pairs=[(n, _url(n) + "/" + raw_url) for n in names])
    for name in cand:
        if budget is not None and not budget.can_attempt():
            tried.append({"mirror": name, "ok": False, "detail": "预算不足，停止镜像降级"})
            break
        r = real(name)
        if r["ok"]:
            return _done(name, raw_url, r, tried)
    return {"ok": False, "channel": "mirror", "third_party": "mirror-pool",
            "elapsed": 0.0, "detail": "镜像池全部失败", "tried": tried}


def git_run(args: list, cwd: str | None, timeout: float, budget=None) -> dict:
    """只读 git 操作经镜像；写操作由上层红线拦截，本函数不做判断。"""
    from channel_direct import git_run as _git
    names = _git_names()
    tried = []
    repo = ""
    for a in args:
        if re.match(r"https?://github\.com/", a):
            repo = a
            break

    def real(name: str) -> dict:
        rt = budget.timeout_for(timeout) if budget is not None else timeout
        r = _git(_git_args(name, args), cwd, rt)
        probe.record(name, bool(r["ok"]), float(r.get("elapsed", 0.0)) * 1000, r.get("detail", ""))
        tried.append({"mirror": name, "ok": r["ok"]})
        return r

    def git_probe(name: str) -> dict:
        # 探活用真 git 协议（ls-remote 很小）：能列出远端引用才算这条镜像对这仓库可用
        return _git(_git_args(name, ["ls-remote", repo, "HEAD"]), None,
                    min(6.0, lines.PROBE["timeout"] + 2))

    cand = probe.candidates(names, probe_fn=(git_probe if repo else None))
    for name in cand:
        if budget is not None and not budget.can_attempt():
            tried.append({"mirror": name, "ok": False, "detail": "预算不足，停止镜像降级"})
            break
        r = real(name)
        if r["ok"]:
            r.update({"channel": "mirror", "via": name, "third_party": name, "tried": tried})
            return r
    return {"ok": False, "channel": "mirror", "third_party": "mirror-pool", "rc": 1,
            "out": "", "err": "mirror pool exhausted", "elapsed": 0.0,
            "detail": "镜像池 git 全部失败", "tried": tried}
