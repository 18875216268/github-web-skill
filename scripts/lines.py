"""内置线路清单（唯一事实源）。

事实依据：2026-09-11 真机实测（CDN 8 域 / 镜像 18 池 / 6 域 IP 候选逐条拨测）。
收录原则：只收实测可用；可用性会漂移——**动态源永远优先于本清单**，
本清单只是"动态源拿不到时"的兜底，且按实测可用性排序（不是性能评比）。
"""
from __future__ import annotations

import os

# ---------- 动态源 ----------
CLOUD_FN_DEFAULT = (os.environ.get("GH_CLOUD_FN")
                    or "https://1317825751-jonkwhxmyb.ap-guangzhou.tencentscf.com")   # 用户自建（GH_CLOUD_FN 可覆盖）
CLOUD_FN_SOURCE = "all"        # ziyou=函数自建探测；all=并入第三方镜像源
CLOUD_FN_TIMEOUT = 15
DOH_SERVERS = ["https://223.5.5.5/resolve", "https://1.12.12.12/resolve"]
DOH_TIMEOUT = 6

# ---------- CDN（单文件读；模板各自不同，新增时带模板即可） ----------
# 收录原则：jsDelivr 官方多边缘域 + 社区公认的等价只读源（statically / githack / gitmirror）。
# **失败 ≠ 失效**：全部保留为候选，运行期由 health 账本排序与冷却，不因某次不可达而删除。
CDN_SOURCES = [
    {"name": "jsdelivr", "url": "https://cdn.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}", "note": "jsDelivr 官方主域"},
    {"name": "jsdelivr-fastly", "url": "https://fastly.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}", "note": "jsDelivr Fastly 边缘"},
    {"name": "jsdelivr-gcore", "url": "https://gcore.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}", "note": "jsDelivr Gcore 边缘"},
    {"name": "jsdelivr-testingcf", "url": "https://testingcf.jsdelivr.net/gh/{owner}/{repo}@{ref}/{path}", "note": "jsDelivr Cloudflare 测试域"},
    {"name": "jsdelivr-bcdn", "url": "https://jsdelivr.b-cdn.net/gh/{owner}/{repo}@{ref}/{path}", "note": "jsDelivr bunny 镜像"},
    {"name": "statically", "url": "https://cdn.statically.io/gh/{owner}/{repo}/{ref}/{path}", "note": "社区公认 jsDelivr 等价源（Statically）"},
    {"name": "githack", "url": "https://raw.githack.com/{owner}/{repo}/{ref}/{path}", "note": "raw.githack（raw 直出）"},
    {"name": "gitmirror-raw", "url": "https://raw.gitmirror.com/{owner}/{repo}/{ref}/{path}", "note": "gitmirror 的 raw 镜像"},
    {"name": "gitcdn", "url": "https://gitcdn.link/repo/{owner}/{repo}/{ref}/{path}", "note": "gitcdn（历史知名，保留候选）"},
]
CDN_TEMPLATES = CDN_SOURCES          # 兼容既有调用

# ---------- 转发代理/镜像源池（只读：HTTP 读 + git 只读） ----------
# 收录原则（三条，落地用户原则）：
#   1) 只收**社区公认、被广泛引用**的源；调研出处（自包含，便于本包独立分发时追溯）：
#      · CSDN《2026 最新收集 GitHub 国内镜像站》（2026-08-13）——文件加速/克隆/界面镜像三类清单
#      · 腾讯云社区转载与极客日志同题清单（2026-03/04）；jsDelivr 官方多边缘域 + statically/githack 为社区公认等价源
#      · 历史知名源（fastgit / cnpmjs / ghps / xget / ghproxy.cc 等）一律保留候选，不因当前不可达删除
#   2) **失败 ≠ 失效**：曾不可达 / 限流 / 漂移的源一律保留为候选——只由运行期账本冷却，绝不删除；
#   3) 动态源优先：云函数 / DoH 等永远是第一优先；本池是"动态源不可用或需 mirror/CDN 兜底"时的候选。
# git 重写样式：默认 `{url}/https://github.com/`（gh-proxy 系）；可用 git_prefix/git_match 覆盖。
MIRROR_SOURCES = [
    # —— 当期实测可用（2026-09-11 真机） ——
    {"name": "gh-proxy.com", "url": "https://gh-proxy.com", "caps": ["http", "git"], "note": "社区主推；实测可用"},
    {"name": "ghfast.top", "url": "https://ghfast.top", "caps": ["http", "git"], "note": "社区高频收录；实测可用"},
    {"name": "gh.xxooo.cf", "url": "https://gh.xxooo.cf", "caps": ["http", "git"], "note": "实测可用"},
    {"name": "gh-proxy.org", "url": "https://gh-proxy.org", "caps": ["http", "git"], "note": "实测可用"},
    {"name": "ghproxy.net", "url": "https://ghproxy.net", "caps": ["http", "git"], "note": "实测可用（支持断点续传）"},
    # —— 社区清单收录（2026 实测榜；保留候选，账本自动择路） ——
    {"name": "ghproxy.homeboyc.cn", "url": "https://ghproxy.homeboyc.cn", "caps": ["http", "git"],
     "note": "评测清单：大体积 Release（1GB+）稳定；2026-09-11 实测两种形态均 403「blocked」——服务器可达但拒绝本调用（可能需 referer/白名单）；保留候选"},
    {"name": "github.akams.cn", "url": "https://github.akams.cn", "caps": ["http", "git"],
     "note": "网页工具站（「GitHub Proxy - 文件下载加速代理」：粘贴链接生成地址）；前缀式直连不适用（两种形态同回 404），接入需逆向其站内 API；保留候选"},
    {"name": "hub.gitmirror.com", "url": "https://hub.gitmirror.com", "caps": ["http", "git"],
     "note": "社区老牌 gitmirror（另有 raw 镜像见 CDN 池）"},
    {"name": "github.moeyy.xyz", "url": "https://github.moeyy.xyz", "caps": ["http", "git"],
     "note": "社区老牌 moeyy 代理"},
    {"name": "ghp.ci", "url": "https://ghp.ci", "caps": ["http"], "note": "社区推荐（简单快捷）"},
    # —— 历史知名 / 曾失效（保留候选：可能恢复） ——
    {"name": "gh-proxy.net", "url": "https://gh-proxy.net", "caps": ["http"],
     "note": "历史：对文件回 HTML 壳页（内容校验会拦截）；保留候选"},
    {"name": "xget.xi-xu.me", "url": "https://xget.xi-xu.me", "caps": ["http"], "note": "历史：曾 429 限流；保留候选"},
    {"name": "ghps.cc", "url": "https://ghps.cc", "caps": ["http"], "note": "历史：可用性漂移；保留候选"},
    {"name": "ghproxy.cc", "url": "https://ghproxy.cc", "caps": ["http"], "note": "历史知名；保留候选"},
    {"name": "hub.fastgit.org", "url": "https://hub.fastgit.org", "caps": ["http", "git"],
     "note": "历史知名（官方停服）；保留候选"},
    {"name": "github.com.cnpmjs.org", "url": "https://github.com.cnpmjs.org", "caps": ["http", "git"],
     "note": "历史知名；保留候选"},
    # —— 换主机式镜像（git_prefix/git_match 与 gh-proxy 系不同） ——
    {"name": "gitclone.com", "url": "https://gitclone.com", "caps": ["git"],
     "git_match": "https://github.com/", "git_prefix": "https://gitclone.com/github.com/",
     "note": "老牌 clone 加速（github.com → gitclone.com/github.com）"},
    {"name": "kkgithub.com", "url": "https://kkgithub.com", "caps": ["git"],
     "git_match": "https://github.com/", "git_prefix": "https://kkgithub.com/",
     "note": "老牌界面镜像（支持按主机名 clone）"},
    {"name": "bgithub.xyz", "url": "https://bgithub.xyz", "caps": ["git"],
     "git_match": "https://github.com/", "git_prefix": "https://bgithub.xyz/",
     "note": "界面镜像（2026 清单收录；git 支持未验证，交给探测）"},
]
MIRROR_HTTP = [s["url"] for s in MIRROR_SOURCES if "http" in s["caps"]]     # 兼容既有调用
MIRROR_GIT = [s["url"] for s in MIRROR_SOURCES if "git" in s["caps"]]       # 兼容既有调用

# ---------- hosts 写入前的严格校验目标（域 → 已知小文件） ----------
# 为什么需要：根路径响应是弱判据——2026-09-11 实测 raw 的 185.199.111.133 根路径 200、
# 真实取文件却 000（10s 超时）。写进系统解析的 IP 必须"能真正取到内容"。
STRICT_PROBE_URLS = {
    "raw.githubusercontent.com": "https://raw.githubusercontent.com/github/gitignore/main/README.md",
}

PROBE = {
    "workers": 7,            # 并发度（标准库线程；每条探测都是独立 curl/git 子进程）
    "timeout": 4.0,          # 单条探测超时（秒）——快速定位不通，立即换源
    "deadline": 6.0,         # 一轮探测整体上限；到点用已返回的最优者
    "fresh_ok_within": 300,  # 账本里"最近成功过"的源直接真取（免探测）的时间窗
    "cooldown_base": 60.0,   # 失败冷却基数：60s × 2^(连败-1)，封顶
    "cooldown_max": 3600.0,  # 冷却封顶（到期自动半开重试；永不删除）
}

# ---------- 钉 IP 的硬编码兜底池（动态源 = 云函数 + DoH，永远先试） ----------
IP_POOLS = {
    "github.com": ["140.82.113.3", "140.82.112.3", "140.82.114.3", "140.82.121.4", "20.205.243.166"],
    "api.github.com": ["20.205.243.168", "140.82.113.6", "140.82.112.6"],
    "codeload.github.com": ["20.205.243.165", "140.82.112.9", "140.82.113.9"],
    "raw.githubusercontent.com": ["185.199.108.133", "185.199.109.133", "185.199.110.133", "185.199.111.133"],
    "gist.githubusercontent.com": ["185.199.108.133", "185.199.109.133", "185.199.110.133", "185.199.111.133"],
    "objects.githubusercontent.com": ["185.199.108.133", "185.199.109.133", "185.199.110.133", "185.199.111.133"],
    # Release 资产（描述里的"Release 下载不动"场景）：重定向目标域，纳入 pin 覆盖
    "release-assets.githubusercontent.com": ["185.199.110.133", "185.199.111.133", "185.199.108.133", "185.199.109.133"],
    "github-releases.githubusercontent.com": ["185.199.110.154", "185.199.111.154", "185.199.108.154", "185.199.109.154"],
}
PIN_DOMAINS = list(IP_POOLS)          # 需要钉 IP 的域名
PIN_CANDIDATES_PER_DOMAIN = 4         # 每域最多试几个候选（云函数已按延迟排序）

# ---------- 缓存与预算默认值 ----------
CACHE_TTL = {"ip": 600}          # 仅 IP 候选缓存；镜像/CDN 的择路已由 probe 健康账本接管
DEFAULT_BUDGET = {"get": 60.0, "git_read": 180.0, "per_call": 120.0,
                  "min_effective": 10.0, "circuit_threshold": 3}   # diag 不设整体预算：各步自带超时
PIN_CONNECT_TIMEOUT = 4.0             # 代理内单 IP 连接超时（实测 12s 太慢会吃掉预算）
