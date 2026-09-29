---
name: github-web-skill
version: "2.2.1"
display_name: "访问GitHub网络"
display_name_en: "GitHub Access Layer"
description: "访问GitHub网络（GitHub 访问层，分场景通道路由）：访问 GitHub 失败时自动逐级降级并如实报告——直连 → 钉 IP → hosts 兜底 → 第三方镜像 → CDN 单文件。当出现 git clone / pull / push 失败、raw 或 Release 下载不动、github.com 打不开、需要「配置 GitHub 加速」、或需要按场景稳定取 GitHub 仓库与文件时使用。也适用于「公司网络访问不了 GitHub」「DNS 污染」「代理环境变量导致命令失败」这类现场。"
description_zh: "网络受限时稳定使用 GitHub 的工具箱：克隆与拉取仓库、下载文件和 Release、修复浏览器打不开 GitHub。自动选最快通道，失败自动换路，hosts 改动可随时回滚。"
description_en: "A toolbox for using GitHub reliably on restricted networks: clone and pull repos, download files and releases, and fix a browser that cannot open github.com. Fastest channel auto-selected, automatic failover, hosts changes always reversible."
license: "MIT"
compatibility: "需要 Python 3.10+（仅标准库）与系统 git/curl；需要出网（GitHub 官方端点、媒体 CDN、第三方镜像池、公共 DoH、外部 hosts 清单源与官方段闸——全部登记于资源层 sources.json）；hosts 通道需管理员权限。"
metadata:
  author: "木小匣"
  update_url: "https://github.com/18875216268/github-web-skill"
  update_policy: "仅显式调用 gh.py update 时检测/下载；本技能从不自检更新（无后台/定时检查）"
  architecture: "routes(总路由) + sources(资源层 hub/collect/speedtest) + channels(方式目录) + scripts(governance: budget/env_guard/report/probe/lines) + update(更新层，仅显式)"
  date: "2026-09-29"
---

# 访问GitHub网络 · github-web-skill（GitHub 访问层）

## 本技能说明

**用于什么**：在网络受限环境下**稳定访问与使用 GitHub 资源**——取单个文件、clone/pull/push 仓库、下载 Release、调用 GitHub API、查看代码页面，以及帮"人"恢复浏览器访问。按场景自动选择通道并逐级降级；全程可编程、可回滚、诚实报告（不假装成功、不编造）。

**何时适用**：
- git clone / pull / push 失败或超时
- raw 文件、Release 资产下载不动
- github.com 打不开、网页图片裂开（图床域名被污染）
- 需要按场景稳定取 GitHub 仓库与文件（"配置 GitHub 加速"）
- 公司网络访问不了 GitHub、DNS 污染、代理环境变量导致命令失败

**何时不适用**：非 GitHub 站点；内网系统访问；需要业务数据的查询（那是其他数据技能的事）；依赖 GitHub 账号认证的操作（SSH 推送、私有仓库与 Packages 的 token 下载——需用户自行配置凭证）。

**面向 Agent（程序化使用）**：
- 唯一入口 `python scripts/gh.py <命令>`：stdout = 单个 JSON（agent 解析），stderr = 一行人类摘要，退出码 `0/1/2/3` 语义化
- 按任务调命令：取文件用 `get`、git 操作用 `git`、帮人修浏览器用 `hosts`、排障先跑 `diag`
- 路由自动发生（场景 → 通道链，见下文〈场景路由〉）；`--force` / `--exclude` 仅用于排障与策略约束
- 每次输出必含：命中通道、是否经第三方、失败原因、下一步建议（`next` 字段）——照着做即可

**面向人（浏览器 / 命令行）**：
- 浏览器打不开 GitHub：先 `hosts --status` 看报告 → 管理员运行 `hosts --apply --yes`（写前自动备份）→ 随时 `hosts --rollback` 恢复
- 也可把本技能当普通命令行工具用（`python scripts/gh.py --help`），安装方式见 `README.md`

## 原则

1. **分类、分场景**：通道各司其职（`routes/routes.json` 是唯一事实源），总路由统一分发。
2. **不评比性能**：只说明每条通道「适合什么 / 作用是什么 / 前提与副作用」；耗时只用于治理参数（超时、预算、熔断）与源健康择路（选择≠评比）。
3. **零系统改动优先**：默认不碰系统；`hosts` 只能显式授权（`--yes`）且必须可回滚。
4. **写操作安全边界**：`push` 等写操作**永不经过第三方镜像**。
5. **零第三方依赖**：Python 标准库 + 系统 git/curl。
6. **并发择优**：镜像 / CDN / IP 探活**全部并发**（完成即用，最快者先试）；单条探测 4s 超时——快速判定不通，立即换源。
   快路径零探测开销（账本热源直取，实测 cdn 0.8~1.0s / mirror 1.6~2.0s）；热源失效才付一轮并发探测（≤6s）。
7. **失败 ≠ 失效**：源池只增不删——任何一次不可达只记"冷却"（指数退避、封顶 1h，到期自动半开重试）；
   内置池收**社区公认**源（含当前不可达者，收录清单与调研出处见资源层 `sources/`），运行时由健康账本（用户区）排序择路。

## 五层架构

```
① 路由层  routes/routes.json（事实源）→ ROUTES.md（渲染产物）；gh.py routes --check 校验
② 资源层    sources/（★v2.2.0：纯外部源，每次全新拉取——hub.py 统一入口 + collect.py 双模式聚合
          （登记型/fetch 驱动型，数据分派）+ speedtest.py 统一测速（策略数据声明）；
          sources.json 唯一数据文件：ip（获取方式 hosts_file/doh/gh_meta）· mirror（登记 68）· cdn（13）；
          增删源=编辑对应节，通道消费声明见 routes.json 的 kinds）
③ 通道层  channels/（6 条通道，**一方式一文件夹**：实现 + README 内部降级链说明；互不知道对方存在）——
          pin/hosts 为**纯应用通道**（零获取逻辑，消费资源层供给）
④ 治理层  scripts/（CLI 为 gh.py + 预算 budget · 环境守卫 env_guard · 报告 report · 并发探测与源账本 probe · 常量 lines）——所有通道共用，通道不得绕过
⑤ 更新层  update/（★v2.1.0：仅显式调用 `gh.py update`——check 只读检测 / apply 需 --yes：staging 校验→
          备份→原地应用→可回滚；本技能**从不自检更新**，无后台/定时检查；更新地址见 manifest.update.url）
```

## 通道一览（按"改动了什么"分类）

| 通道 | 本质（改动了什么） | 作用 / 适合什么 | 前提与副作用 | 第三方 | 授权 |
| --- | --- | --- | --- | --- | --- |
| `direct` | 不改源、不改系统，只走官方端点/协议 | 默认首选：git 元数据、整仓、推送、官方 HTTP 端点 | 无 | 否 | 免 |
| `pin` | 不改源，只绕 DNS/线路：资源层供给 IP 候选（多源聚合+统一测速）→ **单次调用**本地代理按域钉住 | 解析被污染、连接被劣化时的解药；git 与 HTTP 通用 | 首次拉源+测速有前置耗时；零系统改动、进程结束即失效 | 否 | 免 |
| `hosts` | 改**系统解析**（标记块） | 人打不开 GitHub（含浏览器）；`pin` 也救不回时。候选=资源层供给 → 严格校验 → 写入 | 需管理员；写前备份、必须能回滚 | 否 | **显式 --yes** |
| `mirror` | 换入口：第三方转发代理池（**并发探活择优** + 健康账本冷却） | 只读兜底（直连与钉 IP 都失败时） | 流量经第三方；各镜像对 git 协议支持参差 | 是 | 免（报告注明） |
| `cdn` | 换内容来源：媒体 CDN 边缘缓存（**并发探活择优**） | 只读**单个文件**（manifest / README / 小配置） | 只读；分支引用有缓存滞后（正式判定用 tag/commit 固定） | 是 | 免 |
| `offline` | 不联网 | 全部失败后的离线预置与人工指引 | 不实时 | 否 | 免 |

> 传输量乘数：git 只读默认 `shallow`（`clone` 自动 `--depth 1`）——它是参数，不是通道。
> 每条通道的**内部降级链**（源池/择路/超时）与收录原则：见 `channels/<通道名>/README.md`（一方式一文件夹，自包含说明）。

## 场景路由（降级链）

| 场景 | 降级链 |
| --- | --- |
| 取单个文件 | `cdn` → `direct` → `pin` → `mirror` |
| git 只读（ls-remote / fetch / pull / clone） | `direct` → `pin` → `mirror` |
| git 写（push / tag / 提交相关） | `direct` → `pin`（**永不含 mirror**） |
| 解析失败 / 连接劣化 | `pin` → `hosts` → `mirror` |
| 人打不开（浏览器） | `hosts`（先诊断、再授权、可回滚） |
| 全部失败 | `offline`（诚实告知 + 离线指引） |

## 常见任务 → 命令（Agent 速查）

| 你要做的事 | 命令 |
| --- | --- |
| 克隆仓库 / 拉取更新 | `python scripts/gh.py git clone <仓库URL> [目录]`（只读默认自动 `--depth 1`） |
| 查远端版本 / 分支 | `python scripts/gh.py git ls-remote <仓库URL> HEAD` |
| 取仓库里某个文件 | `python scripts/gh.py get owner/repo:path/to/file.txt [--ref main]` |
| 取 Release 资产 / 任意官方下载 | `python scripts/gh.py get --url https://github.com/…/releases/download/…` |
| 先看环境能走哪条通道 | `python scripts/gh.py diag`（`--full`：IP / 镜像 / CDN **并发全量实测**） |
| 排障：只走某条通道 | `get` / `git` 加 `--force direct|pin|mirror|cdn`（写操作禁 `mirror`） |
| 策略约束：排除某些通道 | `get` / `git` 加 `--exclude mirror,cdn`（与 `--force` 互斥；如"不要经第三方"） |
| clone 全链失败、但只要代码 | 看失败报告的 `next` 建议——改取 codeload 归档（zip 快照，无 git 历史） |
| 限制总耗时 | 任何取用命令加 `--deadline <秒>`（默认 get 60s / git 180s） |
| 人打不开 GitHub（浏览器） | `hosts --status` → 报告后 `hosts --apply --yes`；随时 `hosts --rollback` |
| 更新本 Skill（仅你显式要求时） | `update --check`（只读检测）→ `update --apply --yes`（自动备份）；随时 `update --rollback` |
| 自检本 Skill | `python tests/run_tests.py`（`--offline` 跳过出网冒烟） |

## CLI（唯一入口）

```text
python scripts/gh.py diag [--full]                                 # 只读诊断（各通道可用性事实）
python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F] [--deadline S] [--force CH] [--exclude CH,CH]
python scripts/gh.py get --url <https 链接>                         # raw / Release 资产 / codeload 等
python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH] [--exclude CH,CH]   # 包裹 git（自动守卫+预算+降级）
python scripts/gh.py hosts --status | --apply --yes [--flush] | --rollback
python scripts/gh.py routes --check | --render                     # 路由表校验 / 重绘
python scripts/gh.py update --check | --apply --yes | --rollback   # 更新层（仅显式调用，从不自检）
```

退出码：`0` 成功 ｜ `1` 全通道失败 ｜ `2` 需要授权（hosts / update --apply）｜ `3` 用法错误。

`--force <通道>`：只走指定通道（须为 routes.json 已注册通道名；排障与验收常用 `direct|pin|mirror|cdn`；写操作禁 `mirror`，会被红线拒绝）。

## 输出与日志

- stdout：**单个 JSON**（核心字段：`action / ok / channel / via / third_party / elapsed / detail / tried / next`；
  另有各命令专属字段——`get` 的 `file/bytes`、`git` 的 `rc/out/err`、`diag` 的 `checks`、`update` 的 `local/remote/update_available/backup/changes`）
- stderr：一行人类摘要（`--quiet` 关闭）
- 日志：用户区 `~/.github-access/logs/gh-YYYYMM.jsonl`（JSONL，永不写回包内）
- 每次调用**必报**：命中通道、是否经第三方、失败原因、下一步建议

## 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `GH_ACCESS_HOME` | 用户区（日志/缓存/备份） | `~/.github-access` |
| `GH_HOSTS_FILE` | hosts 文件路径（测试/演练用假文件） | 系统 hosts |

> pin 的 IP 候选全部来自**统一资源层**（`sources/hub.py`：hosts 清单源 ×8 + DoH ×5 + 官方段安全闸，
> 并发获取 + 统一测速，每次全新拉取）——无自建服务；全量域清单覆盖浏览器相关全部 GitHub 域。

## 已知边界（明示）

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
