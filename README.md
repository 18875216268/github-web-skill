# 访问GitHub网络（github-web-skill）

> **GitHub 连不上、git clone 失败、文件下载卡住时，用它。**
> 95 个源 + 2 个官方 SSH 端点 · 8 条通道 · 6 个场景路由 · 零第三方依赖（Python 标准库 + 系统 git/curl）

网络受限时让 GitHub 恢复可用：克隆 / 拉取 / 推送仓库、下载单文件与 Release 资产、修好打不开 github.com 的浏览器。
**它不是"收藏了几个加速网址"，而是加速方式的选择与切换机制本身**——按你要做的事自动选定候选通道，每条通道内部并发探活择优，这条真不通才换下一条。

```text
python scripts/gh.py diag      # 唯一入口，先只读诊断：看你的网络能走哪几条路（不改任何东西）
```

**本文档 = 仓库首页**（给 GitHub 读者）。[`SKILL.md`](./SKILL.md) 是同一套结构与事实的 agent / WorkBuddy 版。

**目录**：[1 作用](#1-作用) · [2 最高原则](#2-最高原则) · [3 架构](#3-架构) · [4 通道层](#4-通道层) · [5 资源层](#5-资源层) · [6 入口与参数](#6-入口与参数) · [7 环境变量](#7-环境变量) · [8 输出与日志](#8-输出与日志) · [9 已知边界](#9-已知边界) · [许可](#10-许可)

| 项目 | 内容 |
| --- | --- |
| 名称 | 访问GitHub网络（github-web-skill） |
| 版本 | 2.3.4 |
| 日期 | 2026-10-03 |
| 作者 | 木小匣 |
| 许可 | MIT |
| 更新地址 | https://github.com/18875216268/github-web-skill |

---

## 1. 作用

**GitHub 访问层（GitHub 加速器 / 镜像切换器）**：在网络受限、DNS 被污染、代理环境变量干扰、或者单纯"下载太慢"的环境下，**稳定地** clone / pull / push 仓库、取仓库里的任意文件、下载 Release 资产、调 GitHub API，并帮**人**恢复浏览器访问。

**典型症状（对号入座即可用）**：

| 你遇到的现象 | 本技能怎么处理 |
| --- | --- |
| `git clone` 卡住不动 / 报 `Failed to connect` / 超时 | 依次走 `direct → pin → mirror`，写操作自动排除第三方 |

| `浏览器打不开 GitHub（人肉浏览）` | `hosts` 通道：先诊断 → 授权 → 写前备份 → 随时回滚 | `pin` 钉 IP（零系统改动）；救不回时 `hosts` 修系统解析 |（改 hosts，改前备份、随时回滚）
| `git pull` / `git push` 拉取失败 | 同上；`push` 等写操作**永不经过第三方镜像** |
| `raw.githubusercontent.com` 的文件下载不了或 0 字节 | 走 CDN 边缘缓存 + 内容级校验（拦"200 + 错误页"） |
| Release 资产 / 安装包下载不动 | 走官方端点与镜像转发，预算内自动换源 |
| `github.com` 打不开、网页图片裂开 | `pin` 钉 IP（零系统改动）；救不回时 `hosts` 修系统解析 |
| 浏览器打不开 GitHub（人肉浏览） | `hosts` 通道：先诊断 → 授权 → 写前备份 → 随时回滚 |
| 域名解析到错误 IP / DNS 被污染 | 资源层多源聚合 IP + 官方段安全闸过滤 + 统一测速 |
| 公司网络 / 校园网屏蔽了 GitHub | 多通道并行择路，不死磕单一入口 |
| 命令莫名失败，其实是被代理变量截胡 | `env_guard` 强制清空代理环境变量再执行 |
| 想"配置 GitHub 加速"但不知道选哪个 | 全部内置源池，运行时自动探活择优，**不替你做拍板** |

**不适用**：非 GitHub 站点；内网系统访问；需要业务数据的查询；依赖账号认证的操作（SSH 推送、私有仓库、GitHub Packages 的 token 下载——凭证归你，本技能不碰账号与令牌）。

**怎么装**：不需要 pip 装任何东西。clone 本仓库后直接用：

```text
git clone https://github.com/18875216268/github-web-skill.git
cd github-web-skill
python scripts/gh.py diag          # Windows 可用 py 代替 python
```

## 2. 最高原则

1. **失败 ≠ 失效**：源池**只增不删**——一次不可达只记冷却（指数退避、封顶 1h，到期自动半开重试），绝不因今天挂了就删源。
2. **写操作永不经过第三方**：`push` 等写操作**永不经 `mirror`**（路由表登记 + 运行时拦截 + 验收用例三重锁）。
3. **零系统改动优先**：默认不碰系统；`hosts` 是唯一改系统的通道，必须显式 `--yes` 且**必须可回滚**。
4. **不评比性能**：只说每条通道「适合什么 / 前提与副作用」；耗时仅用于治理参数（超时、预算、熔断）与择路（选择≠评比）。
5. **并发择优**：镜像 / CDN / IP 探活全部并发（完成即用，最快者先试）；单条 4s 超时快速判不通、立即换源。快路径零探测开销（账本热源直取），热源失效才付一轮探测（≤6s）。
6. **诚实报告**：取用类命令（`get`/`git`）每次调用都必报「命中通道 / 是否经第三方 / 失败原因 / 下一步建议」，`tried[]` 全程留痕；全链失败如实说，不编造。
7. **零第三方依赖**：Python 标准库 + 系统 git/curl。

## 3. 架构

### 3.1 目录构造

```
github-web-skill/
├── SKILL.md            # 技能入口：frontmatter（平台路由/上架字段）+ 编号正文（给 agent 读）
├── manifest.json       # 技能声明：版本 / 分层 / 网络白名单 / 写入范围
├── README.md           # 本文件：仓库首页（给 GitHub 读者）
├── LICENSE             # MIT 许可证
├── routes/             # 路由层：routes.json（唯一事实源）+ ROUTES.md（渲染产物）
├── sources/            # 资源层：sources.json（唯一数据文件）+ hub/collect/speedtest + ip/
├── channels/           # 通道层：8 条通道，一通道一文件夹（实现 + 该通道 README）
├── scripts/            # 治理层：gh.py（唯一 CLI）+ budget/env_guard/probe/report/lines
├── update/             # 更新层：仅在你明确要求时才检测和安装更新
└── tests/              # 自检测试：python tests/run_tests.py
```

### 3.2 核心架构（五层）

```
① 路由层  routes/routes.json（唯一事实源）→ ROUTES.md（渲染产物）；gh.py routes --check 双向对账
② 资源层  sources/（纯外部源，每次全新拉取）：hub.py 三池管道（并发获取 → 统一测速 → Top10）
          + collect.py 双模式聚合（登记型 / fetch 驱动型，数据分派）+ speedtest.py 策略注入测速；
          sources.json 为唯一数据文件：ip（hosts_file / doh / gh_meta）· mirror（68）· cdn（13）· ssh（2 官方端点）
③ 通道层  channels/（8 条，一通道一文件夹：实现 + 内部降级链 README；互不知道对方存在）——
          pin / hosts 为纯应用通道（零获取逻辑，只消费资源层供给）；ssh / proxy 不进自动链（见各自 README）
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

> 术语统一：凡指 `channels/` 下的访问方式，一律称**通道**（不再混用"通路 / 路径"）；「获取方式 / 测速方式 / 安装方式」中的"方式"是"方法"义，保留。

## 4. 通道层

### 4.1 通道总表（8 条，按"改动了什么"分类）

| 通道 | 别名（你可能会搜） | 本质（改动了什么） | 适合什么 | 前提与副作用 | 第三方 | 授权 | 支持 git |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `direct` | 直连、官方 | 不改源、不改系统，只走官方端点/协议 | git 元数据、整仓、推送、官方 HTTP 端点 | 无 | 否 | 免 | 是 |
| `pin` | 钉 IP、换 IP、固定 IP | 不改源，只绕 DNS/线路：资源层供给 IP 候选 → **单次调用**本地代理按域钉住 | 解析被污染、连接被劣化时；git 与 HTTP 通用 | 首次拉源+测速有前置耗时；零系统改动、进程结束即失效 | 否 | 免 | 是 |
| `hosts` | 改 hosts、修 hosts | 改**系统解析**（标记块） | 人打不开 GitHub（含浏览器）；`pin` 救不回时 | 需管理员；写前备份、必须可回滚 | 否 | **显式 --yes** | 不适用 |
| `mirror` | 镜像站、镜像、中转 | 换入口：第三方转发代理池（并发探活择优 + 健康账本冷却） | 只读兜底（直连与钉 IP 都失败时） | 流量经第三方；各镜像对 git 支持参差 | 是 | 免（报告注明） | 是（61 = 58 前缀式 + 3 换主机式） |
| `cdn` | 加速节点、边缘缓存 | 换内容来源：媒体 CDN 边缘缓存（并发探活择优） | 只读**单个文件**（manifest / README / 小配置） | 只读；分支引用有缓存滞后（正式判定用 tag/commit 固定） | 是 | 免 | 否 |
| `offline` | 离线兜底 | 不联网 | **约定态**（无实现文件）：全链失败时的链尾——如实报告失败 + 给出下一步建议 | 不实时、不含任何预置数据 | 否 | 免 | 不适用 |
| `ssh` | SSH、22 端口、ssh.github.com | 换传输协议：git 走 SSH（无 SNI、独立端口，HTTPS 被针对性阻断时的逃生族） | **探测双门连通性**（零凭证）；git 语境失败时作为替代传输出现在 offers | 不进自动链；实际走 SSH 需用户自行配置 key（凭证归本通道零接触） | 否（github.com 本尊） | 探测免 / 使用需用户自有 key | 是（仅 git 操作） |
| `proxy` | 用户代理、自有梯子、本地代理 | 换出口：流量经**用户自己的代理**（非共享第三方） | 自有梯子用户的最优路径；显式 `--proxy` 传入即用户已决定 | 仅无认证地址（带凭证直接拒绝）；优先级最高、不走链、失败不静默回退 | 否（用户自有） | 免（显式参数即决定） | 是 |

> 传输量乘数：git 只读默认 `shallow`（`clone` 自动 `--depth 1`）——它是参数，不是通道。
> **别名速查**：加速器 / 梯子 / 稳定访问 → 通道；镜像站 / 镜像 / 中转 → `mirror`；钉 IP / 换 IP / 固定 IP / 绑 IP → `pin`；图快 / 加速节点 / 边缘缓存 → `cdn`；降级 / 兜底 / fallback / 换一条路试 → 场景路由；探活 / 测速 / 择优 → 资源层测速 + 健康账本。
> 每条通道的**内部降级链**（源池/择路/超时）与收录原则：见 `channels/<通道名>/README.md`。

### 4.2 通道 × 场景 交叉矩阵（哪条通道在哪些场景会被用到）

| 场景 \ 通道 | `direct` | `pin` | `hosts` | `mirror` | `cdn` | `offline` | `ssh`（offers） | `proxy`（offers） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 取单个文件 | 第 2 顺位 | 第 3 顺位 | — | 第 4 顺位 | **第 1 顺位** | — | —（raw 不走 SSH） | ✅ 失败时提供 |
| git 只读 | **第 1 顺位** | 第 2 顺位 | — | 第 3 顺位 | 不支持 git | — | ✅ 失败时提供（需 key） | ✅ 失败时提供 |
| git 写（push/tag） | **第 1 顺位** | 第 2 顺位 | — | **禁用**（红线） | 不支持 git | — | ✅ 失败时提供（第三条写逃生路） | ✅ 失败时提供 |
| 解析失败 / 连接劣化 | — | **第 1 顺位** | 第 2 顺位（需授权） | 第 3 顺位 | — | — | ✅ git 语境提供（独立域无 SNI） | ✅ 失败时提供 |
| 人打不开（浏览器） | — | — | **唯一手段** | — | — | — | — | —（浏览器代理属系统设置，不代配） |
| 全部失败 | — | — | — | — | — | **链尾兜底** | ✅ 最后的救命稻草（若门开） | ✅ 最后的救命稻草（若探活通） |

读法：**同一件事在不同场景下走不同的通道序列**——所以本技能不是"一条固定降级链"，
而是「按场景选定候选通道 → 通道内并发择优 → 这条不通才换下一条」。**写操作那一行的 `mirror` 是空的，这是红线。**

### 4.3 通道内部降级链

每条通道自带源级降级链（源池 / 择路 / 超时），互不知道其他通道存在——见 `channels/<通道名>/README.md`。
`hosts` 与 `offline` 不参与 `get` / `git` 的自动降级链：前者需显式授权，后者是链尾约定态，各自服务独立命令。

## 5. 资源层

### 5.1 总览：4 大类 · 95 个源 + 2 个官方 SSH 端点

`sources.json` 是唯一数据文件；每条通道在 `routes/routes.json` 里声明自己消费哪类供给（`kinds` 字段）。
`gh.py routes --check` 做**正向硬校验**（通道声明的 `kinds` 必须真实存在于资源层）+ **反向软提示**（登记了却无通道消费的，只写进 `detail`、不影响退出码）。
**增删源 = 编辑 `sources.json` 对应节。**

| 大类 | 源数 | 获取方式（`ways`） | 测速方式 | 消费通道 | 收录原则 |
| --- | --- | --- | --- | --- | --- |
| `ip` | hosts 清单源 8（**启用 6**）+ DoH 源 5 + 官方段闸 1，覆盖 **42 个 GitHub 域** | `hosts_file`（拉清单）/ `doh`（DNS 解析）/ `gh_meta`（官方 CIDR） | TCP 443 | `pin`、`hosts` | 社区公开清单 + 公共 DoH + GitHub 官方 meta |
| `mirror` | **68** | 纯登记（`sources`） | HTTP HEAD | `mirror` | 社区公认、被广泛引用；含换主机式（`insteadOf`）与仅 http 型 |
| `cdn` | **13** | 纯登记（`sources`） | HTTP HEAD（探针 URL 数据化渲染） | `cdn` | jsDelivr 系边缘 + 公认等价源 |

> `enabled: false` 的源**既不登记也不拉取**（登记型与 fetch 型同一语义）；但白名单对账仍覆盖它们的域名，所以禁用了也不影响 `routes --check`。

### 5.2 `ip` 大类：14 个源（启用 12）/ 42 个域 · 三种获取方式

每次调用全新拉取，不落盘。三种方式：`hosts_file`（HTTP 拉 hosts 文本清单）、`doh`（公共 DNS over HTTPS 解析）、`gh_meta`（GitHub 官方 CIDR 段，用作**安全闸**：候选 IP 必须 ∈ 官方段；端点不可达时静默跳过过滤，不阻塞主流程）。

代表性源：`gitcdn` · `gitee` · `hellogithub520`（GitHub520，21.4k★，每小时更新，**端点非 GitHub**，GitHub 全挂时仍可达）· `ineo6`（**GitLab 端点**，第二条非 GitHub 路径）· `ittuann` · `shidahuilang`；DoH 侧 `alidns-com` · `aliyun` · `dnspod` · `dohpub` · `safe360`。
完整清单与逐条备注见 `sources/sources.json` 与 `sources/ip/`。

### 5.3 `mirror` 大类：68 个第三方转发源（只读；写操作永不经过）

**支持 git 的 58 个**（前缀式 `https://<源>/https://github.com/…` 转发），含社区主推的 `gh-proxy.com` · `ghfast.top` · `ghproxy.net` · `hub.gitmirror.com` · `github.moeyy.xyz` 等。

**仅 git 的 3 个**（**换主机式**：把 `github.com` 整段换成另一个域名）：`gitclone.com` · `kkgithub.com` · `bgithub.xyz`。

**仅 http 读文件的 6 个**：`ghp.ci` · `gh-proxy.net` · `xget.xi-xu.me` · `ghps.cc` · `ghproxy.cc` · `toolwa`。
**仅 Release 的 1 个**：`tuna-github-release`（清华 TUNA，路径映射型，当前通道未支持接线）。

> **为什么有这么多**：源池**只增不删**——一次不可达只记冷却（指数退避、封顶 1h，到期自动半开重试），不因今天挂了就删源。
> 择路靠并发探活 + 用户区健康账本，**不承诺某条源永远可用，但承诺"换源继续试"**。收录标准：社区公认、被广泛引用。
> ⚠️ `ghproxy.net-cf` 与 `ghproxy.net` **是同一个 URL**，但**刻意保留两条**：健康账本按 `name` 分别记延迟与冷却，一条线路劣化时另一条仍会被优先尝试。**不要合并**——所以"68 个源"对应 67 个不同端点，属预期。

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
| 全部失败 | `offline`（诚实告知 + 下一步建议） |

> 链内还有**源级择优**（并发探活取最快），所以实际走的未必是链上第一个——报告里的 `channel` / `via` 才是实际命中的通道与源。
> 用 `--force <通道>` 只走指定通道、`--exclude <通道,...>` 裁剪当前链（如"不要经第三方"），两者互斥。
> `--force` 只接受**有实现的通道**（`direct` / `pin` / `mirror` / `cdn`）；`hosts` 与 `offline` 走各自独立命令，不参与 `--force`。
> ⚠️ **三个场景是说明性的**：`human_access` 由 `hosts` 独立命令承接、`all_failed` 由失败分支的 `next` 承接、`resolve_broken` 是 `pin` 的触发条件——它们**没有独立的自动分支**。

### 6.2 常见任务 → 命令

| 你要做的事 | 命令 |
| --- | --- |
| 克隆仓库 / 拉取更新 | `python scripts/gh.py git clone <仓库URL> [目录]`（只读默认自动 `--depth 1`） |
| 查远端版本 / 分支 | `python scripts/gh.py git ls-remote <仓库URL> HEAD` |
| 取仓库里某个文件 | `python scripts/gh.py get owner/repo:path/to/file.txt [--ref main]` |
| 取 Release 资产 / 任意官方下载 | `python scripts/gh.py get --url https://github.com/…/releases/download/…` |
| 先看环境能走哪条通道 | `python scripts/gh.py diag`（`--full` 并发探活：镜像探 HTTP 能力、IP 每域前 2 个、SSH 双门连通） |
| SSH 门开没开（零凭证，含极端慢门场景） | `python scripts/gh.py ssh --status`（探测 github.com:22 与 ssh.github.com:443；每端点探测总预算 180s） |
| git 走我自己的代理 | `get` / `git` 加 `--proxy http://127.0.0.1:7890`（仅无认证地址；优先级最高、不走链） |
| git 改走 SSH 传输（本次调用） | `git` 加 `--transport ssh`（需你已配置 key；调用级改写，不碰 remote） |
| 声明偏好：以后 git 优先走 SSH | `git` 加 `--prefer-ssh`（门可达即优先；门未开自动按链走并注明） |
| 排障：只走某条通道 | `get` / `git` 加 `--force direct\|pin\|mirror\|cdn` |
| 策略约束：不经第三方 | `get` / `git` 加 `--exclude mirror,cdn` |
| clone 全链失败、但只要代码 | 看失败报告的 `next` 建议——改取 codeload 归档（zip 快照，无 git 历史） |
| 人打不开 GitHub（浏览器） | `hosts --status` → 报告后 `hosts --apply --yes`；随时 `hosts --rollback` |
| 更新本技能（仅你显式要求时） | `update --check`（只读检测）→ `update --apply --yes`（自动备份）；随时 `update --rollback` |
| 自检本技能 | `python tests/run_tests.py`（`--offline` 跳过出网冒烟） |

### 6.3 CLI（唯一入口）

```text
python scripts/gh.py diag [--full]                                 # 只读诊断（各通道可用性事实）
python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F] [--deadline S] [--force CH] [--exclude CH,CH]
python scripts/gh.py get --url <https 链接> [--proxy URL]           # raw / Release 资产 / codeload 等
python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH] [--exclude CH,CH]   # 包裹 git（自动守卫+预算+降级）
python scripts/gh.py git ... [--proxy URL] [--transport ssh] [--prefer-ssh]    # 用户自有出口 / SSH 传输
python scripts/gh.py ssh --status                                  # SSH 双端点连通性（零凭证）
python scripts/gh.py hosts --status | --apply --yes [--flush] | --rollback
python scripts/gh.py routes --check | --render                     # 路由表校验 / 重绘
python scripts/gh.py update --check | --apply --yes | --rollback   # 更新层（仅显式调用，从不自检）
```

| 参数 | 作用 |
| --- | --- |
| `--force <通道>` | 只走指定通道（只接受**有实现**的 `direct`/`pin`/`mirror`/`cdn`；写操作禁 `mirror`，会被红线拒绝） |
| `--exclude <通道,...>` | 裁剪当前场景链（与 `--force` 互斥；排除后链空则如实失败） |
| `--deadline <秒>` | 整体时间预算（默认 get 90s / git 180s / update 60s；预算不足即停止并留痕） |
| `--ref <分支/标签>` | 取文件（`get`）或更新（`update`）时的引用，默认 `main`；正式判定建议用 tag/commit 固定 |
| `--url <https 链接>` | `get` 取任意官方/第三方 https 链接（Release 资产、codeload 等）；此时不走 CDN |
| `--dest <文件>` | 输出落盘路径（不指定则落到用户区 cache 目录） |
| `--cwd <目录>` | `git` 子命令的工作目录 |
| `--full` | `diag` 附带并发探活：镜像按 HTTP 能力、IP 每域前 2 个（**非全量**） |
| `--flush` | `hosts --apply` 后刷新 DNS 缓存——**仅 Windows 生效** |
| `--quiet` | 关闭 stderr 的人类摘要（stdout 的 JSON 不变） |

退出码：`0` 成功 ｜ `1` 失败（未成功——含全通道失败、`routes --check` 校验不通过、`update --check` 拉不到远端）｜ `2` 需要授权/确认（hosts、update --apply、**失败时的 offers 选项**）｜ `3` 用法错误。

### 6.4 两种使用姿势

**给 AI 程序（Agent）**：唯一入口 `python scripts/gh.py <命令>`，stdout = 单个 JSON（直接解析），stderr = 一行人类摘要，退出码 `0/1/2/3` 语义化。按任务调命令：取文件用 `get`、git 操作用 `git`、帮人修浏览器用 `hosts`、排障先跑 `diag`。路由自动发生；`--force` / `--exclude` 仅用于排障与策略约束。

**给命令行使用者（人）**：把它当普通命令行工具用（`python scripts/gh.py --help`）。浏览器打不开 GitHub 时：`hosts --status` 看报告 → 管理员运行 `hosts --apply --yes`（写前自动备份）→ 随时 `hosts --rollback` 恢复。

## 7. 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `GH_ACCESS_HOME` | 用户区（日志 / 缓存 / hosts 备份 / 更新备份） | `~/.github-access` |
| `GH_HOSTS_FILE` | hosts 文件路径（测试 / 演练用假文件） | 系统 hosts |

**环境要求**：Python 3.10+（仅标准库，无需 pip 安装任何东西）· 系统装有 `git` 与 `curl` · 需要出网（GitHub 官方端点 / 媒体 CDN / 第三方镜像池 / 公共 DoH——全部登记在案）· `hosts` 通道需管理员权限（Windows 以管理员运行；Linux/macOS `sudo`）。

> 运行期**零写包内**：日志、缓存、备份全部落在用户区。唯一例外是 `update --apply`（显式 `--yes`，先备份、可回滚）。
> `pin` 的 IP 候选全部来自资源层（hosts 清单源 8 条登记、**启用 6 条** + DoH ×5 + 官方段安全闸，并发获取 + 统一测速，每次全新拉取）——无自建服务。

## 8. 输出与日志

- stdout：**单个 JSON**（agent 直接解析）。核心字段 `action / ok / channel / via / third_party / elapsed / detail / tried / next`；各命令另有专属字段——`get` 的 `file/bytes`、`git` 的 `rc/out/err`、`diag` 的 `checks`、`update` 的 `local/remote/update_available/backup/changes`，以及 `get`/`git` 共有 的 **`budget`**（预算快照：`overall_s / used_s / remaining_s / exceeded`）
- stderr：一行人类摘要（`--quiet` 关闭）
- 日志：用户区 `~/.github-access/logs/gh-YYYYMM.jsonl`（JSONL，永不写回包内）
- 取用类命令**成功时**报：命中通道 `channel`、命中源 `via`、是否经第三方 `third_party`、耗时 `elapsed`
- 取用类命令**失败时**报：试过的每条通道与失败原因 `tried[]`、下一步建议 `next`、预算快照 `budget`（此时**没有** `channel`）
- **怎么读 `budget.exceeded`**：`true` 表示已越过预算上限，该怀疑"超时/预算不够"，而不是"网络彻底不通"；可加大 `--deadline` 重试

### 两个 deadline 的职责边界（别把它们混为一谈）

| 预算 | 作用域 | 默认 | 谁执行 |
| --- | --- | --- | --- |
| **调用预算** | 整条降级链（direct → pin → mirror）的墙钟上限 | get 90s / git 180s（`--deadline` 可改） | `scripts/budget.py` 的 `Budget`，逐层下发 `timeout_for()` |
| **拉源成本** | 资源层"拉一次源 + 测速"的固有成本，**与降级预算正交** | 25s（`sources/hub.py`） | `probe.race` 的守护线程 + deadline |

已知偏差：`pin` 阶段会先拉一次源，这 ~25s**不受调用预算管辖**，所以最坏情况总耗时 ≈ 调用预算 + 25s。全包并发统一用 `probe.race`（**守护线程**）：deadline 到点立即返回、**不阻塞进程退出**。

## 9. 已知边界

- **不碰账号**：SSH **凭证**归你（key 由你生成与保管，本技能零接触）；私有仓库、GitHub Packages 的 token 下载需你自行配置凭证——本技能只处理"网络怎么通"。SSH 传输的**连通性事实**由 `ssh` 通道提供（`gh.py ssh --status`，零凭证）；是否走 SSH 由你决定（`--transport ssh` / `--prefer-ssh`，调用级生效、不碰 remote 配置）。用户代理（`--proxy`）仅收无认证地址——凭证不经过本技能。
- **不上传写操作**：`push` 等写操作永不经过第三方镜像（路由表登记 + 运行时拦截 + 验收用例三重锁）；只读走第三方时会标 `third_party`。
- **Windows 上关闭了证书吊销检查**（`http.schannelCheckRevoke=false`）以换取连通性——**安全换可用性**的取舍。
- `cdn` 只读且不替代 git；分支引用可能滞后，请用 tag/commit 固定。
- `mirror` / `cdn` 是第三方入口，可用性会漂移；**源池只增不删**（不可达只冷却，封顶 1h，到期自动重试），不承诺某条源永远可用，但承诺"换源继续试"。
- `pin` 的 IP 每次全新拉取；IP 可用性随时间漂移，故逐 IP failover。
- `hosts` 需要管理员权限；不会静默改系统（无 `--yes` 必拒绝），写前备份、`--rollback` 必须能恢复。
- **更新**：仅当你显式执行 `gh.py update ...` 时才出网检测/下载（更新地址 https://github.com/18875216268/github-web-skill ）；本技能**从不自检更新**。`--apply` 需 `--yes`：staging 校验（防错包/路径穿越）→ 备份到用户区 → 原地应用 → 可回滚。
- `get --url` 接受**任意 https 链接**（Release 资产、codeload、官方端点等）；带 `--url` 时不再经 CDN（CDN 只按仓库路径取），只走 direct → pin → mirror 且仍做内容校验。

## 10. 许可

MIT（详见 `LICENSE` 文件）。
