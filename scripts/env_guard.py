"""环境守卫：代理清理 + TLS 兼容 + 可执行文件定位。

为什么必须先清代理：沙箱/Agent 环境常注入 http(s)_proxy（127.0.0.1:端口），
git/curl 默认服从它——"直连明明通了、命令却仍然失败"多由此而来（实测踩坑）。
"""
from __future__ import annotations

import locale
import os
import shutil
import sys

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy",
              "NO_PROXY", "no_proxy")   # NO_PROXY 存活会让显式代理被静默旁路，一并清除


def decode_output(raw) -> str:
    """把子进程字节输出解码成文本：先严格试 UTF-8，失败再退到系统本地码页。

    为什么必须这么做：Windows 上 git / curl 的**本地化**错误信息用的是 GBK(cp936)
    等本地码页，不是 UTF-8。2026-10-03 实测踩坑：schannel 的中文报错被
    `encoding="utf-8", errors="replace"` 解成一串 U+FFFD 替换字符，用户完全看不懂——
    而这恰恰是最需要被读懂的失败原因。宁可猜错码页，也不能把错误信息变成乱码。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("gbk", "mbcs", locale.getpreferredencoding(False), "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def clean_env() -> dict:
    """返回清空代理变量后的环境副本（不修改父进程环境）。"""
    env = dict(os.environ)
    for k in PROXY_KEYS:
        env.pop(k, None)
    return env


def proxy_state() -> dict:
    """当前进程可见的代理变量（诊断用事实，不判断好坏）。"""
    return {k: os.environ.get(k) for k in PROXY_KEYS if os.environ.get(k)}


def curl_base(timeout: float, allow_proxy: bool = False) -> list[str]:
    """统一 curl 前缀：默认不走代理环境（防沙箱代理截胡）；显式指定 -x 时保留该代理。

    allow_proxy=True 的场景只有一个：pin 通道要跑自己的本地 CONNECT 代理——
    此时绝不能带 --noproxy '*'，否则会把我们自己的代理也一起关掉（实测踩坑）。
    """
    exe = shutil.which("curl") or ("curl.exe" if sys.platform == "win32" else "curl")
    args = [exe, "--ssl-no-revoke", "-sS", "-m", str(int(max(1, timeout)))]
    if not allow_proxy:
        args += ["--noproxy", "*"]
    return args


def git_config_prefix() -> list[str]:
    """git 的兼容与止损参数：低速即中止；Windows 容忍吊销检查离线。"""
    args = ["-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=10"]
    if sys.platform == "win32":
        args += ["-c", "http.schannelCheckRevoke=false"]
    return args


def have_git() -> bool:
    return shutil.which("git") is not None
