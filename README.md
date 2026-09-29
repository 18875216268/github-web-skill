# github-web-skill · GitHub 访问层

给 **Agent**（也给人）用的 GitHub 访问层：按场景把请求路由到合适通道，失败逐级降级，全程可编程、可回滚、诚实报告。
遵循 [Agent Skills](https://agentskills.io/specification) 规范（入口 `SKILL.md`，`skills-ref validate` 通过 ✓）——**完全独立**，可直接上架 Agent Skills 平台（workbuddy 等）或独立安装。

```
直连 → 钉 IP → hosts 兜底 → 第三方镜像 → CDN 单文件 → 离线指引
```

> 整体链为**全景示意**；实际执行按其**分场景路由**（`routes/routes.json` 唯一事实源）——单文件等场景的通道顺序见 `SKILL.md`〈场景路由（降级链）〉✓

## 特性

- **方式目录化（v2.0.0）**：`channels/<通道名>/` 一方式一文件夹（实现 + 源清单 + README 内部降级链说明）——新增/删除方式只需「放文件 + `routes.json` 注册一行」，`gh.py` 按注册表动态加载，零代码改动。
- **分场景通道路由**：`routes/routes.json` 是唯一事实源，`ROUTES.md` 为渲染产物（含情况×方式矩阵）；`gh.py routes --check` 校验（含注册表双向完整性）、`--render` 重绘。
- **统一资源层**（v2.2.0）：`sources/` 纯外部源、每次全新拉取——`sources.json` 唯一数据文件（`collect.py` 双模式聚合：登记型/fetch 驱动型；测速策略数据声明）——IP 源（hosts 清单源 ×8 + DoH ×5 + 官方段安全闸）、镜像源（登记 68）、CDN 源（13）；增删源 = 编辑对应节。
- **并发择优**：镜像 / CDN / 候选 IP 全部并发探活（完成即用），单条 4s 快速判不通、立即换源；热源命中时零探测开销。
- **失败 ≠ 失效**：源池只增不删——不可达只按指数退避冷却（封顶 1h、到期自动半开重试），由用户区健康账本排序择路。
- **通道可选/可排除**：`--force <通道>` 只走单道；`--exclude ch1,ch2` 裁剪降级链（如"不要经第三方"）；两者互斥。pin/hosts 为**纯应用通道**（零获取逻辑，消费资源层供给）。
- **更新层（v2.1.0）**：仅显式调用 `gh.py update` 才出网——`--check` 只读检测 / `--apply` 需 `--yes`（staging 校验 → 备份 → 原地应用 → 可回滚）；本技能**从不自检更新**（无后台/定时检查）。更新地址：`https://github.com/18875216268/github-web-skill`。
- **Agent 友好**：stdout = 单个 JSON（含 `channel/via/third_party/tried/next`）；stderr = 一行人类摘要；用户区 JSONL 留痕；退出码 `0/1/2/3` 语义化。
- **零系统改动优先**：`hosts` 只能显式授权（`--yes`）、写前备份、必可回滚；写操作**永不经过第三方镜像**。
- **零第三方依赖**：Python 标准库 + 系统 `git` / `curl`。

## 快速开始

```bash
python scripts/gh.py diag                                  # 1) 先看环境能走哪条通道（--full 出全量并发实测）
python scripts/gh.py get owner/repo:path/to/file.txt       # 2) 取单个文件（自动降级）
python scripts/gh.py get --url https://github.com/…/releases/download/…   # Release 资产 / 任意 https
python scripts/gh.py get owner/repo:file.txt --exclude cdn # 3) 策略约束：不经 CDN（与 --force 互斥）
python scripts/gh.py git clone https://github.com/owner/repo.git          # 4) 包裹 git（自动守卫+预算+降级）
python scripts/gh.py hosts --status                        # 5) 人打不开 GitHub 时的兜底（需授权）
python scripts/gh.py update --check                        # 6) 检测本技能更新（仅显式调用，从不自检）
```

自检（离线可跑）：

```bash
python tests/run_tests.py              # 全量（含真机只读冒烟）
python tests/run_tests.py --offline    # 跳过出网冒烟
```

作为 Skill 安装：把本目录放进宿主的技能目录（如 CodeBuddy 的 `~/.codebuddy/skills/github-web-skill/`）即可被自动加载；
也可只当命令行工具用（`python scripts/gh.py --help`）。

## 目录结构

```
github-web-skill/
├── SKILL.md            # 入口：原则 / 通道一览 / 场景路由 / 命令速查 / 边界（先读这个）
├── manifest.json       # 声明：版本 / 分层 / 网络白名单 / shell / 写入范围
├── README.md           # 本文件（人读）
├── LICENSE             # MIT
├── routes/             # routes.json（事实源）+ ROUTES.md（渲染产物）
├── sources/            # ★资源层：纯外部源，每次全新拉取（hub.py + collect.py 双模式聚合 + speedtest.py；
│                       #   sources.json 唯一数据文件 + ip/[fetch_hosts, fetch_doh, fetch_ghmeta]）
├── channels/           # 方式目录：一方式一文件夹（channel_*.py 实现 + README 内部降级链说明；零获取逻辑）
├── scripts/            # gh.py（唯一 CLI）+ 治理件（budget/env_guard/report/probe/lines）
├── update/             # ★更新层（v2.1.0）：仅显式调用（check / apply --yes / rollback；从不自检）
└── tests/              # 9 个测试文件 + 总入口
```

## 环境要求

- Python 3.10+（仅标准库）；系统 `git` 与 `curl`
- 出网：GitHub 官方端点 / 媒体 CDN / 第三方镜像池 / 公共 DoH / 外部 hosts 清单源与官方段闸（全部登记于资源层 `sources/`，`hub.py --check` 对账）
- `hosts` 通道需要管理员权限（Windows：以管理员运行；Linux/macOS：`sudo`）

环境变量：`GH_ACCESS_HOME`（用户区，默认 `~/.github-access`）· `GH_HOSTS_FILE`（假 hosts，演练用）。

## 边界（明示）

- 第三方镜像 / CDN 可用性会漂移：本 Skill 的处理是"并发探活 + 换源 + 冷却重试 + 如实报告"，不承诺某条源永远可用。
- `cdn` 只读单文件，不替代 git；分支引用有缓存滞后，正式判定请用 tag/commit 固定。
- `hosts` 只动自己的标记块（`# github-web-skill Start/End`），删除该块即恢复原状；未通过存活校验的 IP 不会写入。

## 更新

更新地址：**<https://github.com/18875216268/github-web-skill>**（远端 `main` 分支 `manifest.json` 为版本事实源）。

本技能**从不自检更新**——无后台线程、无定时检查，其他任何命令都不附带版本检测；仅当你显式要求时才出网：

```bash
python scripts/gh.py update --check          # 检测（只读，比版本；报告 local/remote/update_available）
python scripts/gh.py update --apply --yes    # 应用（staging 校验 → 自动备份 → 原地替换；可回滚）
python scripts/gh.py update --rollback       # 回滚到最近一次更新前
```

细节与安全边界见 `update/README.md`。

## 许可

MIT（见 `LICENSE`）。

## 作者

**木小匣**
