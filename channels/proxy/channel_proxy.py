"""通道 proxy：用户自有出口（显式 --proxy 传入；无源类、不进自动降级链）。

职责边界（单开铁律 + 凭证红线）：
- 无源类：代理地址来自运行时参数 --proxy（用户自有出口），不是外部清单——不设源类、
  不进 sources.json、不进自动降级链（显式传入即用户已决定，直接执行；失败如实报告并重新 offers）；
- 凭证红线：**只收无认证代理**——带 user:pass@ 的地址直接拒绝（凭证不经过本技能，
  也不进入日志/JSONL 留痕）。本机代理（127.0.0.1）通常无需认证，已覆盖绝大多数场景；
- 与 env_guard 的关系：env_guard 清空的是"环境注入的代理"（沙箱假代理有前科）；
  --proxy 是用户显式决定，二者不冲突——显式传入时代理以调用参数形态精确生效。
"""
from __future__ import annotations

ALLOWED_SCHEMES = ("http://", "https://", "socks5://", "socks5h://")


def validate(url: str) -> tuple:
    """校验用户传入的代理地址。返回 (ok, why)。

    规则（2026-10-08 设计定稿）：
    - 只收 http/https/socks5(h) 协议；
    - **拒绝带认证的代理**（含 @ 的 userinfo）——凭证不经过本技能，也不进入日志；
    - 拒绝空值与含空格的值。
    """
    u = (url or "").strip()
    if not u:
        return False, "代理地址为空"
    if "@" in u:
        return False, ("不接受带认证的代理（user:pass@host:port）——凭证不经过本技能；"
                       "请改用无认证代理（本机代理通常无需认证）")
    if " " in u:
        return False, "代理地址含空格"
    if not u.lower().startswith(ALLOWED_SCHEMES):
        return False, "代理协议仅支持 http/https/socks5(h)（收到：%s）" % u[:48]
    return True, ""
