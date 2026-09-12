"""通道 direct：不改源、不改系统——只走官方端点与官方协议。

作用：默认首选。git 元数据 / 整仓 / 推送，以及官方 HTTP 端点（raw / api / codeload）。
前提：本机 DNS 与线路可达官方域名；不做任何绕行。
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import env_guard


def head_ok(url: str, timeout: float) -> dict:
    """HEAD 探活（并发择优用）：2xx/3xx = 可服务；其余如实记录。

    两条加固（2026-09-11 实测结论）：
    - **瞬时失败重试一次**：并发探测下本地 DNS/TCP 会偶发抖动（实测同一源 137ms 失败、单独测 2.7s 200）；
    - **405 兼容**：部分服务器不支持 HEAD，改 `-r 0-0` 小范围 GET 复探，避免把"不支持 HEAD"误判为不可用。
    """
    t0 = time.perf_counter()

    def run(method_args: list) -> str:
        args = (env_guard.curl_base(timeout) + method_args
                + ["-L", "--max-redirs", "5", "-o", os.devnull, "-w", "%{http_code}", url])
        try:
            p = subprocess.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                               timeout=timeout + 3)
        except Exception:
            return "000"
        return ((p.stdout or "").strip().splitlines() or ["000"])[-1]

    code = run(["-I"])
    if code == "000":                       # 瞬时抖动：立刻重试一次（不通 = 快速换源，而不是直接冷却）
        code = run(["-I"])
    if code == "405":                       # 不支持 HEAD → 用极小范围 GET 复探
        code = run(["-r", "0-0"])
    ms = (time.perf_counter() - t0) * 1000
    return {"ok": code.startswith(("2", "3")), "ms": round(ms, 1), "code": code,
            "detail": "HEAD %s" % code}


def http_get(url: str, dest: Path, timeout: float, extra: list | None = None) -> dict:
    t0 = time.perf_counter()
    extra = extra or []
    allow_proxy = "-x" in extra            # 只有显式代理（pin 通道）才保留代理
    args = (env_guard.curl_base(timeout, allow_proxy=allow_proxy)
            + ["-L", "--max-redirs", "5", "-o", str(dest), "-w", "%{http_code}", *extra, url])
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=env_guard.clean_env(),
                           timeout=timeout + 6)
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "curl 超时", "elapsed": round(time.perf_counter() - t0, 2)}
    except FileNotFoundError:
        return {"ok": False, "detail": "未找到 curl", "elapsed": 0.0}
    code = (p.stdout or "").strip().splitlines()[-1:] or ["000"]
    # 只认 2xx：301/302 是"重定向说明"不是文件内容（fastly 域实测会 301 跳去 raw——曾把 3xx 当成功）
    ok = code[0].startswith("2") and dest.exists() and dest.stat().st_size > 0
    return {"ok": ok, "detail": "HTTP %s" % code[0], "elapsed": round(time.perf_counter() - t0, 2),
            "err": (p.stderr or "").strip()[:160]}


_BAD_PREFIXES = (b"404: not found", b"404 not found", b"couldn't find the requested file",
                 b"<html", b"<!doctype html")


def content_sane(dest: Path, path: str) -> tuple:
    """内容级校验：拦"200 + 错误页/壳页"（镜像与 CDN 都有这种历史，不能只看状态码）。

    对 `.html/.htm` 目标豁免 HTML 判据（网页本身就是 HTML）。
    """
    try:
        head = dest.read_bytes()[:160]
    except Exception:
        return False, "读不到内容"
    low = head.lower().lstrip()
    if not low:
        return False, "内容为空"
    if low.startswith((b"<html", b"<!doctype html")) and not path.lower().endswith((".html", ".htm")):
        return False, "内容像 HTML 壳页/错误页"
    for bad in _BAD_PREFIXES[:3]:
        if low.startswith(bad):
            return False, "内容像错误说明（%s…）" % head[:32]
    return True, ""


def git_run(args: list, cwd: str | None, timeout: float) -> dict:
    t0 = time.perf_counter()
    if not env_guard.have_git():
        return {"ok": False, "detail": "未安装 git", "elapsed": 0.0, "rc": -1, "out": "", "err": ""}
    cmd = ["git", *env_guard.git_config_prefix(), *args]
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           env=env_guard.clean_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "git 超时", "elapsed": round(time.perf_counter() - t0, 2),
                "rc": 124, "out": "", "err": "timed out"}
    return {"ok": p.returncode == 0, "rc": p.returncode, "out": p.stdout, "err": p.stderr,
            "detail": "git rc=%d" % p.returncode, "elapsed": round(time.perf_counter() - t0, 2)}
