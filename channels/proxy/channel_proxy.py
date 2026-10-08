"""通道 proxy：用户自有出口（显式 --proxy 传入；无源类、不进自动降级链）。

职责边界（单开铁律 + 凭证红线）：
- 无源类：代理地址来自运行时参数 --proxy（用户自有出口），不是外部清单——不设源类、
  不进 sources.json、不进自动降级链（显式传入即用户已决定，直接执行；失败如实报告并重新 offers）；
- 凭证红线（宽松判定，2026-10-08 用户裁决）：**只拦"带密码"的代理**（user:pass@host:port，
  userinfo 含冒号）——密码是凭证，不经过本技能、不进日志。裸用户名（user@host）与
  path/query 里的 @ 一律放行（它们不构成可用密码，且为合法 URL）。
- 与 env_guard 的关系：env_guard 清空的是"环境注入的代理"（沙箱假代理有前科）；
  --proxy 是用户显式决定，二者不冲突——显式传入时代理以调用参数形态精确生效。
"""
from __future__ import annotations

from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http://", "https://", "socks5://", "socks5h://")


def validate(url: str) -> tuple:
    """校验用户传入的代理地址。返回 (ok, why)。

    规则（2026-10-08 放松版）：
    - 只收 http/https/socks5(h) 协议；
    - **仅拒绝 user:pass@ 形式**（urlsplit 的 netloc 权威段含 @ 且 userinfo 含冒号
      = 带密码）——裸 user@、path/query 中的 @ 均放行；
    - 拒绝空值与含空白的值。
    """
    u = (url or "").strip()
    if not u:
        return False, "代理地址为空"
    if any(c.isspace() for c in u):
        return False, "代理地址含空白字符"
    if not u.lower().startswith(ALLOWED_SCHEMES):
        return False, "代理协议仅支持 http/https/socks5(h)（收到：%s）" % u[:48]
    try:
        netloc = urlsplit(u).netloc
    except ValueError:
        return False, "代理地址无法解析"
    if "@" in netloc:
        userinfo = netloc.rsplit("@", 1)[0]
        if ":" in userinfo:                       # user:pass@ —— 密码就是凭证
            return False, ("不接受带密码的代理（user:pass@host:port）——密码不经过本技能、"
                           "不进日志；裸用户名（user@host）可放行")
    return True, ""
