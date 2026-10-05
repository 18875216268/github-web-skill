---
name: github-web-skill
version: "2.2.3"
display_name: "访问GitHub网络"
display_name_en: "GitHub Access Layer"
description: "帮助用户轻松访问 GitHub 网络，突破GitHub网络限制（GitHub限速、无法访问等），特别是当遇上 git clone / pull / push 失败或超时、raw 文件与 Release 资产下载不动、github.com 打不开、浏览器进不去、DNS 污染导致解析到错误 IP、公司网络与校园网屏蔽 GitHub、代理环境变量让命令莫名失败、网速慢拉不动仓库等情况时，本技能可快速提供 GitHub 一键加速、github 镜像站自动切换、修改 hosts 修复浏览器访问、受限网络下 clone 仓库与下载文件等能力！实现多源、多通道智能路由，按你的网络情况个性化制定访问方案，全流程自动择优、失败自动换路，结果如实报告、改系统随时可回滚。"
description_zh: "帮助用户轻松访问 GitHub，突破网络限制（限速、无法访问等）！让GitHub访问变得更加迅捷。如遇连不上、clone 失败超时、文件与 Release 下载卡住、github.com 打不开、浏览器进不去、DNS 污染、公司网络与校园网屏蔽、代理干扰时，可实现多源多通道智能路由，并提供一键加速、镜像站自动切换、修改 hosts 等能力，失败自动换路、自动择优、如实报告、改 hosts 可回滚，为用户稳定访问GitHub保驾护航。"
description_en: "Reach GitHub on restricted networks: clone and pull repos, download files and releases, fix a browser that cannot open github.com. 95 sources across 6 channels, routed automatically — fastest first, automatic failover, hosts changes reversible."
triggers: 帮我下载 GitHub 上的 github-web-skill 项目；浏览器 GitHub 访问不了，请为我修复；部署项目到 GitHub 时 git push 连不上/推送失败
examples_zh:
  - 帮我下载 GitHub 上的 github-web-skill 项目
  - 浏览器 GitHub 访问不了，请为我修复
  - 部署项目到 GitHub 时 git push 连不上/推送失败
examples_en:
  - Download the github-web-skill project from GitHub for me
  - My browser can't open GitHub — please fix my access
  - git push to GitHub fails or times out when I deploy my project
license: "MIT"
compatibility: "需要 Python 3.10+（仅标准库）与系统 git/curl；需要出网（GitHub 官方端点、媒体 CDN、第三方镜像池、公共 DoH、外部 hosts 清单源与官方段闸——全部登记于资源层 sources.json）；hosts 通道需管理员权限。"
metadata:
  author: "木小匣"
  update_url: "https://github.com/18875216268/github-web-skill"
  update_policy: "仅显式调用 gh.py update 时检测/下载；本技能从不自检更新（无后台/定时检查）"
  architecture: "routes(总路由) + sources(资源层 hub/collect/speedtest) + channels(通道目录) + scripts(governance: budget/env_guard/report/probe/lines) + update(更新层，仅显式)"
  date: "2026-10-03"
---

# 访问GitHub网络（github-web-skill）· GitHub 加速、镜像、hosts 智能路由

> **一句话**：GitHub 连不上、git clone 失败、文件下载卡住时，用它。
> **规模**：95 个源 · 6 条通道 · 6 个场景路由 · 零第三方依赖（Python 标准库 + 系统 git/curl）

## 1. 作用

一个 **GitHub 访问层（GitHub 加速器 / 镜像切换器）**：在网络受限、DNS 被污染、代理环境变量干扰、或者单纯"下载太慢"的环境下，
**稳定地** clone / pull / push 仓库、取仓库里的任意文件、下载 Release 资产、调 GitHub API，并帮**人**恢复浏览器访问。

它不是"收藏了几个加速网址"，而是**加速方式的选择与切换机制本身**：按你要做的事自动选定候选通道，
每条通道内部并发探活择优（挑当下最通的那条），这条真不通才换下一条；全程可编程、可回滚、诚实报告（不假装成功、不编造）。

**典型症状（对号入座即可用）**：

| 你遇到的现象 | 本技能怎么处理 |
| --- | --- |
| `git clone` 卡住不动 / 报 `Failed to connect` / 超时 | 依次走 `direct → pin → mirror`，写操作自动排除第三方 |
| `git pull` / `git push` 拉取失败 | 同上；`push` 等写操作**永不经过第三方镜像** |
| `raw.githubusercontent.com` 的文件下载不了或 0 字节 | 走 CDN 边缘缓存 + 内容级校验（拦"200 + 错误页"） |
| Release 资产 / 安装包下载不动 | 走官方端点与镜像转发，预算内自动换源 |
| `github.com` 打不开、网页图片裂开 | `pin` 钉 IP（零系统改动）；救不回时 `hosts` 修系统解析 |
| 浏览器打不开 GitHub（人肉浏览） | `hosts` 通道：先诊断 → 授权 → 写前备份 → 随时回滚 |
| 域名解析到错误 IP / DNS 被污染 | 资源层多源聚合 IP + 官方段安全闸过滤 + 统一测速 |
| 公司网络 / 校园网屏蔽了 GitHub | 多通道并行择路，不死磕单一入口 |
| 命令莫名失败，其实是没走代理 | `env_guard` 强制清空代理环境变量再执行 |
| 想"配置 GitHub 加速"但不知道选哪个 | 全部内置源池，运行时自动探活择优，**不替你做拍板** |

**换个说法你可能在找它**（常见问法索引）：GitHub 打不开 · 连不上 · 访问不了 · 无法访问 · 拉不下来 · 下载不了 · 下载速度慢 · github 加速 · github 镜像站 · 镜像 · 加速器 · 梯子 · 代理变量干扰 · DNS 污染 · 公司网络屏蔽 GitHub · 校园网 · hosts 修复

**何时不适用**：非 GitHub 站点；内网系统访问；需要业务数据的查询；依赖 GitHub 账号认证的操作
（SSH 推送、私有仓库、GitHub Packages 的 token 下载——需你自行配置凭证；本技能不碰你的账号与令牌）。

**30 秒上手**：

```text
python scripts/gh.py diag     # 只读诊断：先看你的网络到底能走哪条路（唯一入口，不改任何东西）
```

**两个高频问法**：

- **`git clone` 失败怎么办？** → `python scripts/gh.py git clone <仓库URL>`。自动按场景链试，只读自动 `--depth 1`；全链失败会如实告诉你试过什么，并建议改取 codeload 归档（zip 快照）。
- **哪个 GitHub 镜像站最好用？** → **不替你排名**（镜像站可用性漂移快）。它并发探活取最快 + 账本按延迟排序 + 失败只冷却不删源，**不用你挑，它自己挑，坏了自动跳过**。

## 2. 最高原则

1. **失败 ≠ 失效**：源池**只增不删**——一次不可达只记冷却（指数退避、封顶 1h，到期自动半开重试），绝不因今天挂了就删源。
2. **写操作永不经过第三方**：`push` 等写操作**永不经 `mirror`**（路由表登记 + 运行时拦截 + 验收用例三重锁）。
3. **零系统改动优先**：默认不碰系统；`hosts` 是唯一改系统的通道，必须显式 `--yes` 且**必须可回滚**。
4. **不评比性能**：只说每条通道「适合什么 / 前提与副作用」；耗时仅用于治理参数（超时、预算、熔断）与择路（选择≠评比）。
5. **并发择优**：镜像 / CDN / IP 探活全部并发（完成即用，最快者先试）；单条 4s 超时快速判不通、立即换源。快路径零探测开销（账本热源直取），热源失效才付一轮探测（≤6s）。
6. **诚实报告**：取用类命令（`get`/`git`）每次调用都必报「命中通道 / 是否经第三方 / 失败原因 / 下一步建议」，`tried[]` 全程留痕；全链失败如实说，不编造。
7. **零第三方依赖**：Python 标准库 + 系统 git/curl，`pip` 无需装任何东西。

## 3. 架构

### 3.1 目录构造

```
github-web-skill/
├── SKILL.md            # 技能入口：frontmatter（平台路由/上架字段）+ 编号正文（给 agent 读）
├── manifest.json       # 技能声明：版本 / 分层 / 网络白名单 / 写入范围
├── README.md           # 仓库首页文档（给 GitHub 读者；结构与本文档一致，措辞面向人）
├── LICENSE             # MIT 许可证
├── routes/             # 路由层：routes.json（唯一事实源）+ ROUTES.md（渲染产物）
├── sources/            # 资源层：sources.json（唯一数据文件）+ hub/collect/speedtest + ip/
├── channels/           # 通道层：6 条通道，一通道一文件夹（实现 + 该通道 README）
├── scripts/            # 治理层：gh.py（唯一 CLI）+ budget/env_guard/probe/report/lines
├── update/             # 更新层：仅在你显式要求时才检测和安装更新
└── tests/              # 自检测试：python tests/run_tests.py
```

**两份文档的分工**：`SKILL.md` 给 agent 与 WorkBuddy 平台（frontmatter 决定何时启用）；`README.md` 给 GitHub 访客（结构与事实一致，措辞面向人）。

### 3.2 核心架构（五层）

```
① 路由层  routes/routes.json（唯一事实源）→ ROUTES.md（渲染产物）；gh.py routes --check 双向对账
② 资源层  sources/（纯外部源，每次全新拉取）：hub.py 三池管道（并发获取 → 统一测速 → Top10）
          + collect.py 双模式聚合（登记型 / fetch 驱动型，数据分派）+ speedtest.py 策略注入测速；
          sources.json 为唯一数据文件：ip（hosts_file / doh / gh_meta）· mirror（68）· cdn（13）
③ 通道层  channels/（6 条，一通道一文件夹：实现 + 内部降级链 README；互不知道对方存在）——
          pin / hosts 为纯应用通道（零获取逻辑，只消费资源层供给）
④ 治理层  scripts/（唯一 CLI 是 gh.py，另有 budget 预算 · env_guard 环境守卫 · probe 并发探测与源账本·
          report 报告 · lines 常量）——所有通道共用，通道不得绕过
⑤ 更新层  update/（仅显式调用 gh.py update：check 只读检测 / apply 需 --yes：
          staging 校验 → 备份 → 原地应用 → 可回滚；**从不自检更新**，无后台与定时检查）
```

| 层 | 事实源 | 改动它意味着 |
| --- | --- | --- |
| 路由 | `routes/routes.json` | 改走法（用哪些通道、什么顺序、哪些红线）——**零改码** |
| 资源 | `sources/sources.json` | 改源池（加/删镜像站、加域名）——**零改码** |
| 通道 | `channels/<名>/channel_<名>.py` | 加一条新通道——放文件 + 注册一行，**零改码** |
| 治理 | `scripts/` | 改预算 / 报告口径 / 探测参数 |
| 更新 | `update/update.py` | 改更新与回滚流程 |

> 术语统一：凡指`channels/` 下的访问方式，一律称**通道**（不再混用"通路 / 路径"）；「获取方式 / 测速方式 / 安装方式」中的"方式"是"方法"义，保留。`routes.json` 的 `kinds` 声明通道消费哪类供给。

## 4. 通道层

### 4.1 通道总表（6 条，按"改动了什么"分类）

| 通道 | 别名（你可能会搜） | 本质（改动了什么） | 作用 / 适合什么 | 前提与副作用 | 第三方 | 授权 | 支持 git |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `direct` | 直连、官方 | 不改源、不改系统，只走官方端点/协议 | 默认首选：git 元数据、整仓、推送、官方 HTTP 端点 | 无 | 否 | 免 | 是 |
| `pin` | 钉 IP、换 IP、固定 IP | 不改源，只绕 DNS/线路：资源层供给IP 候选（多源聚合+统一测速）→ **单次调用**本地代理按域钉住 | 解析被污染、连接被劣化时的解药；git 与 HTTP 通用 | 首次拉源+测速有前置耗时；零系统改动、进程结束即失效 | 否 | 免 | 是 |
| `hosts` | 改 hosts、修 hosts | 改**系统解析**（标记块） | 人打不开 GitHub（含浏览器）；`pin` 也救不回时。候选=资源层供给 → 严格校验 → 写入 | 需管理员；写前备份、必须能回滚 | 否 | **显式 --yes** | 不适用 |
| `mirror` | 镜像站、镜像、中转 | 换入口：第三方转发代理池（**并发探活择优** + 健康账本冷却） | 只读兜底（直连与钉 IP 都失败时） | 流量经第三方；各镜像对 git 协议支持参差 | 是 | 免（报告注明） | 是（61 = 58 前缀式 + 3 换主机式） |
| `cdn` | 加速节点、边缘缓存 | 换内容来源：媒体 CDN 边缘缓存（**并发探活择优**） | 只读**单个文件**（manifest / README / 小配置） | 只读；分支引用有缓存滞后（正式判定用 tag/commit 固定） | 是 | 免 | 否（只读文件） |
| `offline` | 离线兜底 | 不联网 | **约定态**（无实现文件）：全链失败时的链尾——如实报告失败 + 给出下一步建议 | 不实时、不含任何预置数据 | 否 | 免 | 不适用 |

> 传输量乘数：git 只读默认 `shallow`（`clone` 自动 `--depth 1`）——它是参数，不是通道。
> **别名速查**：加速器 / 梯子 / 稳定访问 → 通道；镜像站 / 镜像 / 中转 → `mirror`；钉 IP / 换 IP / 固定 IP / 绑 IP → `pin`；图快 / 加速节点 / 边缘缓存 → `cdn`；降级 / 兜底 / fallback / 换一条路试 → 场景路由；探活 / 测速 / 择优 → 资源层测速 + 健康账本。
> 每条通道的**内部降级链**（源池/择路/超时）与收录原则：见 `channels/<通道名>/README.md`（一通道一文件夹，自包含说明）。

### 4.2 通道 × 场景 交叉矩阵（哪条通道在哪些场景会被用到）

| 场景 \ 通道 | `direct` | `pin` | `hosts` | `mirror` | `cdn` | `offline` |
| --- | --- | --- | --- | --- | --- | --- |
| 取单个文件 | 第 2 顺位 | 第 3 顺位 | — | 第 4 顺位 | **第 1 顺位** | — |
| git 只读 | **第 1 顺位** | 第 2 顺位 | — | 第 3 顺位 | 不支持 git | — |
| git 写（push/tag） | **第 1 顺位** | 第 2 顺位 | — | **禁用**（红线） | 不支持 git | — |
| 解析失败 / 连接劣化 | — | **第 1 顺位** | 第 2 顺位（需授权） | 第 3 顺位 | — | — |
| 人打不开（浏览器） | — | — | **唯一手段** | — | — | — |
| 全部失败 | — | — | — | — | — | **链尾兜底** |

读法：**同一件事在不同场景下走的是不同的通道序列**——所以本技能不是"一条固定降级链"，
而是"按场景选定候选通道 → 通道内并发择优 → 这条不通才换下一条"。**写操作那一行的 `mirror` 是空的，这是红线。**

### 4.3 通道内部降级链

每条通道自带源级降级链（源池 / 择路 / 超时），互不知道其他通道存在——见 `channels/<通道名>/README.md`。
`hosts` 与 `offline` 不参与 `get` / `git` 的自动降级链：前者需显式授权，后者是链尾约定态，各自服务独立命令。

## 5. 资源层

### 5.1 总览：3 大类 · 95 个源

`routes/routes.json` 里每条通道都声明了自己**消费哪类供给**（`kinds` 字段）。`gh.py routes --check` 做的是
**正向硬校验**（通道声明的 `kinds` 必须真实存在于资源层，声明了不存在的供给即失败）+ **反向软提示**
（资源层登记了却无通道消费的，只写进 `detail`、不影响退出码）——所以通道表与下面的源表不会各说各话。**增删源 = 编辑 `sources.json` 对应节。**

| 大类 | 源数 | 获取方式（`ways`） | 测速方式 | 消费通道 | 收录原则 |
| --- | --- | --- | --- | --- | --- |
| `ip` | hosts 清单源 8（**启用 6**）+ DoH 源 5 + 官方段闸 1，覆盖 **42 个 GitHub 域** | `hosts_file`（拉清单）/ `doh`（DNS 解析）/ `gh_meta`（官方 CIDR） | TCP 443 | `pin`、`hosts` | 社区公开清单 + 公共 DoH + GitHub 官方 meta |
| `mirror` | **68** | 纯登记（`sources`） | HTTP HEAD | `mirror` | 社区公认、被广泛引用；含换主机式（`insteadOf`）与仅 http 型 |
| `cdn` | **13** | 纯登记（`sources`） | HTTP HEAD（探针 URL 数据化渲染） | `cdn` | jsDelivr 系边缘 + 公认等价源 |

### 5.2 `ip` 大类：14 个源（启用 12）/ 42 个域 · 三种获取方式（每次调用全新拉取，不落盘）

| 方式 | 源 | 域名 / 地址 | 备注 |
| --- | --- | --- | --- |
| `hosts_file`<br>（拉 hosts 文本） | `gitcdn` | `hosts.gitcdn.top/hosts.txt` | 社区 hosts 清单 |
| | `gitee` | `gitee.com/if-the-wind/github-hosts/raw/main/hosts` | 社区 hosts 清单 |
| | `hellogithub520` | `raw.hellogithub.com/hosts` | GitHub520（21.4k★），每小时更新；**端点非 GitHub**，GitHub 全挂时仍可达 |
| | `ineo6` | `gitlab.com/ineo6/hosts/-/raw/master/next-hosts` | 每小时更新；**GitLab 端点**，第二条非 GitHub 路径 |
| | `ittuann` | `raw.githubusercontent.com/ittuann/GitHub-IP-hosts/main/hosts` | 活跃更新；依赖 GitHub raw（鸡生蛋，低优先） |
| | `shidahuilang` | `raw.githubusercontent.com/shidahuilang/hosts/main/hosts` | 每日更新；依赖 GitHub raw（低优先候选） |
| | `fast-github-access` | `namegenliang.github.io/fast-github-access/...` | 每 2 小时同步；实测 HTTP 4xx，暂不启用 |
| | `feng2208` | `raw.githubusercontent.com/feng2208/github-hosts/main/hosts` | 实测 404，暂不启用 |
| `doh`<br>（DNS 解析） | `alidns-com` | `dns.alidns.com/resolve` | 阿里（域名形式，与 IP 形式互为备份） |
| | `aliyun` | `223.5.5.5/resolve` | 阿里公共 DoH |
| | `dnspod` | `1.12.12.12/resolve` | DNSPod 公共 DoH |
| | `dohpub` | `doh.pub/dns-query` | 腾讯 DNSPod（域名形式） |
| | `safe360` | `doh.360.cn/resolve` | 360 安全 DNS |
| `gh_meta`<br>（安全闸） | `gh_meta` | `api.github.com/meta` | GitHub 官方 CIDR 段：候选 IP 必须 ∈ 官方段；端点不可达时**静默跳过过滤**，不阻塞主流程 |

> `enabled: false` 的源**既不登记也不拉取**（登记型与 fetch 型同一语义）；但白名单对账仍覆盖它们的域名，所以禁用了也不影响 `routes --check`。

### 5.3 `mirror` 大类：68 个第三方转发源（只读；写操作永不经过）

**支持 git 的 58 个**（前缀式 `https://<源>/https://github.com/…` 转发）：

```text
gh-proxy.com · ghfast.top · gh.xxooo.cf · gh-proxy.org · ghproxy.net · ghproxy.homeboyc.cn
github.akams.cn · hub.gitmirror.com · github.moeyy.xyz · hub.fastgit.org · github.com.cnpmjs.org
gh.qninq.cn · ghm.078465.xyz · ghproxy.net-cf · down.mxw.xx.kg · gh.jjj.gv.uy · githubdog.com
ghproxy.imciel.com · gh.idayer.com · ghproxy.cxkpro.top · gh.acmsz.top · 777.z321.cc.cd · gh.monlor.com
ghp.keleyaa.com · github.ednovas.xyz · ghfile.geekertao.top · gitproxy.mrhjx.cn · gh.927223.xyz
gh.07150721.xyz · tvv.tw · cfgh.ikgy.top · gh.jasonzeng.dev · github.geekery.cn · gh.noki.eu.org
git.yylx.win · gh.noki.icu · gh.sixyin.com · jiashu.1win.eu.org · fastgit.cc · gh.dpik.top
github.tbap.top · github.mxw.qzz.io · gh.inkchills.cn · proxy.vvvv.ee · gh.my-website.ccwu.cc
gh.felicity.ac.cn · gg.z321.cc.cd · gh.catmak.name · gh.meali.top · ghproxy.monkeyray.net · gh.chjina.com
githubfast.com · hub.yzuu.cf · github.hscsec.cn · hub.nuaa.cf · hub.gitfast.pro · github-ur1-fun · nite07
```

**仅 git 的 3 个**（**换主机式**：不是路径前缀，而是把 `github.com` 整段换成另一个域名）：

| 源 | insteadOf 目标 | 备注 |
| --- | --- | --- |
| `gitclone.com` | `https://gitclone.com/github.com/` | 老牌 clone 加速 |
| `kkgithub.com` | `https://kkgithub.com/` | 老牌界面镜像 |
| `bgithub.xyz` | `https://bgithub.xyz/` | 界面镜像 |

**仅 http 读文件的 6 个**（不能用于 git）：

| 源 | 备注 |
| --- | --- |
| `ghp.ci` | 社区推荐 |
| `gh-proxy.net` | 历史：会回 HTML 壳页，由内容校验拦截；保留候选 |
| `xget.xi-xu.me` | 历史：曾 429 限流；保留候选 |
| `ghps.cc` | 历史：可用性漂移；保留候选 |
| `ghproxy.cc` | 历史知名；保留候选 |
| `toolwa` | 网页生成器型（无编程前缀接口），当前不启用 |

**仅 Release 的 1 个**：`tuna-github-release`（`mirrors.tuna.tsinghua.edu.cn/github-release`，路径映射型，当前通道未支持接线）。

> **为什么有这么多**：源池**只增不删**——任何一次不可达只记"冷却"（指数退避、封顶 1h，到期自动半开重试），
> 不会因为今天挂了就被删掉。择路靠并发探活 + 用户区健康账本，**不承诺某条源永远可用，但承诺"换源继续试"**。
> 增删源 = 编辑 `sources/sources.json` 的对应节（`routes --check` 自动对账）。
> ⚠️ `ghproxy.net-cf` 与 `ghproxy.net` **是同一个 URL**，但**刻意保留两条**：健康账本按 `name` 分别记延迟与冷却，
> 一条线路劣化时另一条仍会被优先尝试。**不要合并**——所以"68 个源"对应 67 个不同端点，属预期。

### 5.4 `cdn` 大类：13 个边缘缓存源（只读单个文件）

| 分组 | 源 | 路径规则 |
| --- | --- | --- |
| jsDelivr 系边缘 | `jsdelivr` · `jsdelivr-fastly` · `jsdelivr-gcore` · `jsdelivr-testingcf` · `jsdelivr-bcdn` | `/gh/{owner}/{repo}@{ref}/{path}`（与主域一致；`jsdelivr-bcdn` 是 bunny 镜像，非 jsDelivr 官方域） |
| 公认等价源 | `statically` · `githack` · `gitmirror-raw` · `gitcdn` | 各家自有规则，多为 `/gh/` 或 `/{owner}/{repo}/{ref}/{path}` |
| JSDMirror 系（腾讯云 EdgeOne） | `jsdmirror` · `jsdmirror-admincdn` · `jsdmirror-radishzz` · `jsdmirror-sikao123` | **与 jsDelivr 完全一致**，国内直连友好 |

> CDN 只读**单文件**、不替代 git；分支引用有缓存滞后，正式判定请用 tag/commit 固定。

## 6. 入口与参数

### 6.1 场景路由（降级链）

| 场景 | 降级链 |
| --- | --- |
| 取单个文件 | `cdn` → `direct` → `pin` → `mirror` |
| git 只读（ls-remote / fetch / pull / clone） | `direct` → `pin` → `mirror` |
| git 写（push / tag / 提交相关） | `direct` → `pin`（**永不含 mirror**） |
| 解析失败 / 连接劣化 | `pin` → `hosts` → `mirror` |
| 人打不开（浏览器） | `hosts`（先诊断、再授权、可回滚） |
| 全部失败 | `offline`（诚实告知 + 离线指引） |

> 链内还有**源级择优**（并发探活取最快），所以实际走的未必是链上第一个——报告里的 `channel` / `via` 才是实际命中的通道与源。
> 用 `--force <通道>` 只走指定通道、`--exclude <通道,...>` 裁剪当前链（如"不要经第三方"），两者互斥。
> `--force` 只接受**有实现的通道**（`direct` / `pin` / `mirror` / `cdn`）；`hosts` 与 `offline` 走各自独立命令，不参与 `--force`。
> ⚠️ **三个场景是说明性的**：`human_access` 由 `hosts` 独立命令承接、`all_failed` 由失败分支的 `next` 承接、`resolve_broken` 是 `pin` 的触发条件（解析/线路劣化时自动进入）——它们**没有独立的自动分支**。

### 6.2 常见任务 → 命令

| 你要做的事 | 命令 |
| --- | --- |
| 克隆仓库 / 拉取更新 | `python scripts/gh.py git clone <仓库URL> [目录]`（只读默认自动 `--depth 1`） |
| 查远端版本 / 分支 | `python scripts/gh.py git ls-remote <仓库URL> HEAD` |
| 取仓库里某个文件 | `python scripts/gh.py get owner/repo:path/to/file.txt [--ref main]` |
| 取 Release 资产 / 任意官方下载 | `python scripts/gh.py get --url https://github.com/…/releases/download/…` |
| 先看环境能走哪条通道 | `python scripts/gh.py diag`（`--full` 并发探活：镜像探 HTTP 能力、IP 每域前 2 个） |
| 排障：只走某条通道 | `get` / `git` 加 `--force direct|pin|mirror|cdn`（写操作禁 `mirror`） |
| 策略约束：排除某些通道 | `get` / `git` 加 `--exclude mirror,cdn`（与 `--force` 互斥；如"不要经第三方"） |
| clone 全链失败、但只要代码 | 看失败报告的 `next` 建议——改取 codeload 归档（zip 快照，无 git 历史） |
| 限制总耗时 | 任何取用命令加 `--deadline <秒>`（默认 get 60s / git 180s） |
| 人打不开 GitHub（浏览器） | `hosts --status` → 报告后 `hosts --apply --yes`；随时 `hosts --rollback` |
| 更新本 Skill（仅你显式要求时） | `update --check`（只读检测）→ `update --apply --yes`（自动备份）；随时 `update --rollback` |
| 自检本 Skill | `python tests/run_tests.py`（`--offline` 跳过出网冒烟） |

### 6.3 CLI（唯一入口）

```text
python scripts/gh.py diag [--full]                                 # 只读诊断（各通道可用性事实）
python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F] [--deadline S] [--force CH] [--exclude CH,CH]
python scripts/gh.py get --url <https 链接>                         # raw / Release 资产 / codeload 等
python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH] [--exclude CH,CH]   # 包裹 git（自动守卫+预算+降级）
python scripts/gh.py hosts --status | --apply --yes [--flush] | --rollback
python scripts/gh.py routes --check | --render                     # 路由表校验 / 重绘
python scripts/gh.py update --check | --apply --yes | --rollback   # 更新层（仅显式调用，从不自检）
```

退出码：`0` 成功 ｜ `1` 失败（未成功——含全通道失败、`routes --check` 校验不通过、`update --check` 拉不到远端）｜ `2` 需要授权（hosts / update --apply）｜ `3` 用法错误。

| 参数 | 作用 |
| --- | --- |
| `--force <通道>` | 只走指定通道（只接受**有实现**的 `direct`/`pin`/`mirror`/`cdn`；写操作禁 `mirror`，会被红线拒绝） |
| `--exclude <通道,...>` | 裁剪当前场景链（与 `--force` 互斥；排除后链空则如实失败） |
| `--deadline <秒>` | 整体时间预算（默认 get 60s / git 180s / update 60s；预算不足即停止并留痕）。**仅 get / git / update 接受此参数**——diag / hosts / routes 不需要预算，不认它 |
| `--ref <分支/标签>` | 取文件（`get`）或更新（`update`）时的引用，默认 `main`；正式判定建议用 tag/commit 固定 |
| `--url <https 链接>` | `get` 取任意官方/第三方 https 链接（Release 资产、codeload 等）；此时不走 CDN |
| `--dest <文件>` | 输出落盘路径（不指定则落到用户区 cache 目录） |
| `--cwd <目录>` | `git` 子命令的工作目录 |
| `--full` | `diag` 附带并发探活：镜像按 HTTP 能力、IP 每域前2 个（**非全量**） |
| `--flush` | `hosts --apply` 后刷新 DNS 缓存——**仅 Windows 生效**（其它平台传了也不报错但不做任何事） |
| `--quiet` | 关闭 stderr 的人类摘要（stdout 的 JSON 不变） |

### 6.4 面向 Agent 与面向人

**面向 Agent（程序化使用）**

- 唯一入口 `python scripts/gh.py <命令>`：stdout = 单个 JSON（agent 直接解析），stderr = 一行人类摘要，退出码 `0/1/2/3` 语义化
- 按任务调命令：取文件用 `get`、git 操作用 `git`、帮人修浏览器用 `hosts`、排障先跑 `diag`
- 路由自动发生（场景 → 通道链，见 6.1）；`--force` / `--exclude` 仅用于排障与策略约束
- 取用类命令（`get` / `git`）成功时输出必含：命中通道 `channel`、命中源 `via`、是否经第三方 `third_party`；失败时输出必含 `tried[]` 与 `next`——照着做即可

**面向人（浏览器 / 命令行）**

- 浏览器打不开 GitHub：先 `hosts --status` 看报告 → 管理员运行 `hosts --apply --yes`（写前自动备份）→ 随时 `hosts --rollback` 恢复
- 也可当普通命令行工具用（`python scripts/gh.py --help`），安装方式见 `README.md`

## 7. 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `GH_ACCESS_HOME` | 用户区（日志 / 缓存 / hosts 备份 / 更新备份） | `~/.github-access` |
| `GH_HOSTS_FILE` | hosts 文件路径（测试 / 演练用假文件） | 系统 hosts |

> 运行期**零写包内**：日志、缓存、备份全部落在用户区。唯一例外是 `update --apply`（显式 `--yes`，先备份、可回滚）。
> `pin` 的 IP 候选全部来自资源层（`sources/hub.py`：hosts 清单源 8 条登记、**启用 6 条** + DoH ×5 + 官方段安全闸，
> 并发获取 + 统一测速，每次全新拉取）——无自建服务。

## 8. 输出与日志

- stdout：**单个 JSON**（agent 直接解析）。核心字段 `action / ok / channel / via / third_party / elapsed / detail / tried / next`；
  各命令另有专属字段——`get` 的 `file/bytes`、`git` 的 `rc/out/err`、`diag` 的 `checks`、`update` 的 `local/remote/update_available/backup/changes`，
  以及 `get`/`git` 共有 的 **`budget`**（预算快照：`overall_s / used_s / remaining_s / exceeded`）
- stderr：一行人类摘要（`--quiet` 关闭）
- 日志：用户区 `~/.github-access/logs/gh-YYYYMM.jsonl`（JSONL，永不写回包内）
- 取用类命令（`get` / `git`）**成功时**报：命中通道 `channel`、命中源 `via`、是否经第三方 `third_party`、耗时 `elapsed`、落盘 `file`/`bytes`（git 为 `rc`/`out`/`err`）
- 取用类命令**失败时**报：试过的每条通道与失败原因 `tried[]`、下一步建议 `next`、预算快照 `budget`（此时**没有** `channel`——没有通道成功，自然无命中通道）；
  `git` 另报 **`err`**（最后一条通道的 git stderr 原文）——**失败原因必须可读**，不能只给一个 `rc=128`
- **`next` 会区分病因**：命中认证类特征（`Permission to` / `Authentication failed` / `could not read Username` / `403`）时，
  `next` 额外提示"这是凭据/授权问题，不是网络问题，换通道无用"；网络类失败则不提示，避免误导
- **子进程输出按本地码页解码**：Windows 上 git / curl 的中文报错是 GBK(cp936) 而非 UTF-8，
  统一走 `env_guard.decode_output()` 解码——**失败原因里不会出现乱码**
- **怎么读 `budget.exceeded`**：`true` 表示已越过预算上限，该怀疑"超时/预算不够"，而不是"网络彻底不通"；可加大 `--deadline` 重试
- 独立命令（`hosts` / `routes` / `update` / `diag`）按各自语义输出，不套用上面两条

### 两个 deadline 的职责边界（别把它们混为一谈）

| 预算 | 作用域 | 默认 | 谁执行 |
| --- | --- | --- | --- |
| **调用预算** | 整条降级链（direct → pin → mirror）的墙钟上限 | get 60s / git 180s（`--deadline` 可改） | `scripts/budget.py` 的 `Budget`，逐层下发 `timeout_for()` |
| **拉源成本** | 资源层"拉一次源 + 测速"的固有成本，**与降级预算正交** | 25s（`sources/hub.py`） | `probe.race` 的守护线程 + deadline |

已知偏差：`pin` 阶段会先拉一次源，这 ~25s**不受调用预算管辖**，
所以最坏情况总耗时 ≈ 调用预算 + 25s。全包并发统一用 `probe.race`（**守护线程**）：
deadline 到点立即返回、**不阻塞进程退出**——这是硬约束，禁止改用非守护线程池。

## 9. 已知边界

- **不碰账号**：不支持 SSH 推送、私有仓库、GitHub Packages 的 token 下载——需你自行配置凭证；本技能只处理"网络怎么通"。
- **不上传写操作**：`push` 等写操作永不经过第三方镜像（路由表登记 + 运行时拦截 + 验收用例三重锁）；只读走第三方时会标 `third_party`。
- **写操作救不回网络封锁**：`pin` 只绕过 **DNS 解析层与线路质量层**（换域名→实测可用 IP 直连，见 `channels/pin/channel_pin.py` 的 CONNECT 代理）；
  若网络在 **IP 层或端口层**阻断（按 IP 丢包、封 443、深度检测 TLS），`push` 等写操作**无法救回**——因为唯一可行的绕法是走第三方镜像，而那是红线。
  此时 `next` 会如实建议换网络或自行配置代理/SSH 凭证。**"部署"一词只覆盖推送这段网络问题，不含 CI/CD 与 GitHub Pages。**
- **Windows 上关闭了证书吊销检查**（`http.schannelCheckRevoke=false`）以换取连通性——这是**安全换可用性**的取舍，特此明示。
- `cdn` 只读且不替代 git；分支引用可能滞后，请用 tag/commit 固定。
- `mirror` / `cdn` 是第三方入口，可用性会漂移；**源池只增不删**——不可达只冷却（指数退避、封顶 1h），
  到期自动重试；择路靠并发探活 + 用户区健康账本，不承诺某条源永远可用，但承诺"换源继续试"。
  收录标准：社区公认、被广泛引用（调研清单与出处见 `sources.json` 的 kinds.mirror 节与 README——本包自包含）。
- `pin` 的 IP 候选全部来自资源层（`sources/hub.py` 多源聚合+统一测速，每次全新拉取）；IP 可用性随时间漂移，故逐 IP failover。
- `hosts` 需要管理员权限；本 Skill 不会静默改系统（无 `--yes` 必拒绝），并保留备份供回滚。
- **更新**：仅当你显式执行 `gh.py update ...` 时才出网检测/下载（更新地址 `https://github.com/18875216268/github-web-skill`）；
  本 Skill **从不自检更新**——无后台线程、无定时检查，`diag` 等其他命令一律不附带版本检测。
  `--apply` 需 `--yes`：staging 校验（防错包/路径穿越）→ 备份到用户区 → 原地应用 → 可回滚。
- `get --url` 接受**任意 https 链接**（Release 资产、codeload、官方端点等）；带 `--url` 时不再经 CDN（CDN 只按仓库路径取），只走 direct → pin → mirror 且仍做内容校验。
