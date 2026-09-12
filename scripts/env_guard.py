"""环境守卫：代理清理 + TLS 兼容 + 可执行文件定位。

为什么必须先清代理：沙箱/Agent 环境常注入 http(s)_proxy（127.0.0.1:端口），
git/curl 默认服从它——"直连明明通了、命令却仍然失败"多由此而来（实测踩坑）。
"""
from __future__ import annotations

import os
import shutil
import sys

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")


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
