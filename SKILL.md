---
name: github-web-skill
description: "GitHub 访问层（分场景通道路由）：访问 GitHub 失败时自动逐级降级并如实报告——直连 → 钉 IP → hosts 兜底 → 第三方镜像 → CDN 单文件。当出现 git clone / pull / push 失败、raw 或 Release 下载不动、github.com 打不开、需要「配置 GitHub 加速」、或需要按场景稳定取 GitHub 仓库与文件时使用。也适用于「公司网络访问不了 GitHub」「DNS 污染」「代理环境变量导致命令失败」这类现场。"
license: "MIT"
compatibility: "需要 Python 3.10+（仅标准库）与系统 git/curl；需要出网（GitHub 官方端点、媒体 CDN、第三方镜像池、用户自建云函数、DoH）；hosts 通道需管理员权限。"
metadata:
  version: "1.1.2"
  architecture: "routes(总路由) + channels(原子通道) + governance(budget/env_guard/report/probe)"
  date: "2026-09-11"
---

# github-web-skill · GitHub 访问层

给 **Agent** 用的 GitHub 访问层：按场景把请求路由到合适的通道，逐级降级；全程可编程、可回滚、诚实报告。
CLI 面向 Agent（stdout = 单个 JSON），日志与摘要面向人（stderr + 用户区留痕）。

## 原则

1. **分类、分场景**：通道各司其职（`routes/routes.json` 是唯一事实源），总路由统一分发。
2. **不评比性能**：只说明每条通道「适合什么 / 作用是什么 / 前提与副作用」；耗时只用于治理参数（超时、预算、熔断）与源健康择路（选择≠评比）。
3. **零系统改动优先**：默认不碰系统；`hosts` 只能显式授权（`--yes`）且必须可回滚。
4. **写操作安全边界**：`push` 等写操作**永不经过第三方镜像**。
5. **零第三方依赖**：Python 标准库 + 系统 git/curl。
6. **并发择优**：镜像 / CDN / IP 探活**全部并发**（完成即用，最快者先试）；单条探测 4s 超时——快速判定不通，立即换源。
   快路径零探测开销（账本热源直取，实测 cdn 0.8~1.0s / mirror 1.6~2.0s）；热源失效才付一轮并发探测（≤6s）。
7. **失败 ≠ 失效**：源池只增不删——任何一次不可达只记"冷却"（指数退避、封顶 1h，到期自动半开重试）；
   内置池收**社区公认**源（含当前不可达者，见 `lines.py` 收录原则），运行时由健康账本（用户区）排序择路。

## 三层架构

```
① 路由层  routes/routes.json（事实源）→ ROUTES.md（渲染产物）；gh.py routes --check 校验
② 通道层  6 条通道（5 个有实现、互不知道对方存在；`offline` 是约定态、无实现文件）——可单独测、可替换
③ 治理层  预算(budget) · 环境守卫(env_guard) · 报告(report) · 并发探测与源账本(probe) —— 所有通道共用，通道不得绕过
```

## 通道一览（按"改动了什么"分类）

| 通道 | 本质（改动了什么） | 作用 / 适合什么 | 前提与副作用 | 第三方 | 授权 |
| --- | --- | --- | --- | --- | --- |
| `direct` | 不改源、不改系统，只走官方端点/协议 | 默认首选：git 元数据、整仓、推送、官方 HTTP 端点 | 无 | 否 | 免 |
| `pin` | 不改源，只绕 DNS/线路：云函数/DoH 取 IP → **单次调用**本地代理钉 IP | 解析被污染、连接被劣化时的解药；git 与 HTTP 通用 | 首次取候选有前置耗时；零系统改动、进程结束即失效 | 否 | 免 |
| `hosts` | 改**系统解析**（标记块） | 人打不开 GitHub（含浏览器）；`pin` 也救不回时 | 需管理员；写前备份、必须能回滚 | 否 | **显式 --yes** |
| `mirror` | 换入口：第三方转发代理池（**并发探活择优** + 健康账本冷却） | 只读兜底（直连与钉 IP 都失败时） | 流量经第三方；各镜像对 git 协议支持参差 | 是 | 免（报告注明） |
| `cdn` | 换内容来源：媒体 CDN 边缘缓存（**并发探活择优**） | 只读**单个文件**（manifest / README / 小配置） | 只读；分支引用有缓存滞后（正式判定用 tag/commit 固定） | 是 | 免 |
| `offline` | 不联网 | 全部失败后的离线预置与人工指引 | 不实时 | 否 | 免 |

> 传输量乘数：git 只读默认 `shallow`（`clone` 自动 `--depth 1`）——它是参数，不是通道。

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
| 限制总耗时 | 任何取用命令加 `--deadline <秒>`（默认 get 60s / git 180s） |
| 人打不开 GitHub（浏览器） | `hosts --status` → 报告后 `hosts --apply --yes`；随时 `hosts --rollback` |
| 自检本 Skill | `python tests/run_tests.py`（`--offline` 跳过出网冒烟） |

## CLI（唯一入口）

```text
python scripts/gh.py diag [--full]                                 # 只读诊断（各通道可用性事实）
python scripts/gh.py get <owner>/<repo>:<path> [--ref R] [--dest F] [--deadline S] [--force CH]
python scripts/gh.py get --url <https 链接>                         # raw / Release 资产 / codeload 等
python scripts/gh.py git <git 参数...> [--cwd D] [--deadline S] [--force CH]   # 包裹 git（自动守卫+预算+降级）
python scripts/gh.py hosts --status | --apply --yes [--flush] | --rollback
python scripts/gh.py routes --check | --render                     # 路由表校验 / 重绘
```

退出码：`0` 成功 ｜ `1` 全通道失败 ｜ `2` 需要授权（hosts）｜ `3` 用法错误。

`--force <通道>`：只走指定通道（排障与验收用；写操作禁 `mirror`，会被红线拒绝）。

## 输出与日志

- stdout：**单个 JSON**（字段：`action / ok / channel / via / third_party / elapsed / detail / tried / next`；`via`、`third_party` 视场景出现）
- stderr：一行人类摘要（`--quiet` 关闭）
- 日志：用户区 `~/.github-access/logs/gh-YYYYMM.jsonl`（JSONL，永不写回包内）
- 每次调用**必报**：命中通道、是否经第三方、失败原因、下一步建议

## 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `GH_ACCESS_HOME` | 用户区（日志/缓存/备份） | `~/.github-access` |
| `GH_HOSTS_FILE` | hosts 文件路径（测试/演练用假文件） | 系统 hosts |
| `GH_CLOUD_FN` | 取可达 IP 的云函数地址 | 用户自建云函数（内置默认） |

> 云函数协议（换自建函数时按此对接）：`GET <GH_CLOUD_FN>/?source=all` 返回**纯文本**，每行 `IP<空白>域名`；
> `alive.<域>` 视为该域的"实测存活"标记（会被归一化到 `<域>` 且排候选最前）。解析失败/超时不报错，自动降级到 DoH 与内置池。

## 已知边界（明示）

- `cdn` 只读且不替代 git；分支引用可能滞后，请用 tag/commit 固定。
- `mirror` / `cdn` 是第三方入口，可用性会漂移；**源池只增不删**——不可达只冷却（指数退避、封顶 1h），
  到期自动重试；择路靠并发探活 + 用户区健康账本，不承诺某条源永远可用，但承诺"换源继续试"。
  收录标准：社区公认、被广泛引用（调研清单与出处见 `scripts/lines.py` 注释——本包自包含，不依赖包外文档）。
- `pin` 的 IP 来源优先级：云函数 → DoH → 内置硬编码池；IP 可用性随时间漂移，故每次取候选并逐 IP failover。
- `hosts` 需要管理员权限；本 Skill 不会静默改系统（无 `--yes` 必拒绝），并保留备份供回滚。
- `get --url` 接受**任意 https 链接**（Release 资产、codeload、官方端点等）；带 `--url` 时不再经 CDN（CDN 只按仓库路径取），只走 direct → pin → mirror 且仍做内容校验。
