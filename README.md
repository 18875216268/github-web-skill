# github-web-skill · GitHub 访问层

给 **Agent**（也给人）用的 GitHub 访问层：按场景把请求路由到合适通道，失败逐级降级，全程可编程、可回滚、诚实报告。
遵循 [Agent Skills](https://agentskills.io/specification) 规范（`skills-ref validate` 通过）。

```
直连 → 钉 IP → hosts 兜底 → 第三方镜像 → CDN 单文件 → 离线指引
```

## 特性

- **分场景通道路由**：`routes/routes.json` 是唯一事实源，`ROUTES.md` 为渲染产物；`gh.py routes --check` 校验、`--render` 重绘。
- **并发择优**：镜像 / CDN / 候选 IP 全部并发探活（完成即用），单条 4s 快速判不通、立即换源；热源命中时零探测开销。
- **失败 ≠ 失效**：源池只增不删——不可达只按指数退避冷却（封顶 1h、到期自动半开重试），由用户区健康账本排序择路。
- **Agent 友好**：stdout = 单个 JSON；stderr = 一行人类摘要；用户区 JSONL 留痕；退出码 `0/1/2/3` 语义化。
- **零系统改动优先**：`hosts` 只能显式授权（`--yes`）、写前备份、必可回滚；写操作**永不经过第三方镜像**。
- **零第三方依赖**：Python 标准库 + 系统 `git` / `curl`。

## 快速开始

```bash
python scripts/gh.py diag                                  # 1) 先看环境能走哪条通道（--full 出全量并发实测）
python scripts/gh.py get owner/repo:path/to/file.txt       # 2) 取单个文件（自动降级）
python scripts/gh.py get --url https://github.com/…/releases/download/…   # Release 资产 / 任意 https
python scripts/gh.py git clone https://github.com/owner/repo.git          # 3) 包裹 git（自动守卫+预算+降级）
python scripts/gh.py hosts --status                        # 4) 人打不开 GitHub 时的兜底（需授权）
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
├── scripts/            # gh.py（唯一 CLI）+ 通道实现 + 治理件（budget/env_guard/report/probe）
└── tests/              # 7 个测试文件（118 项断言）+ 总入口
```

## 环境要求

- Python 3.10+（仅标准库）；系统 `git` 与 `curl`
- 出网：GitHub 官方端点 / 媒体 CDN / 第三方镜像池 / 用户自建云函数（`GH_CLOUD_FN` 可换）/ DoH
- `hosts` 通道需要管理员权限（Windows：以管理员运行；Linux/macOS：`sudo`）

环境变量：`GH_ACCESS_HOME`（用户区，默认 `~/.github-access`）· `GH_HOSTS_FILE`（假 hosts，演练用）· `GH_CLOUD_FN`（取可达 IP 的云函数）。

## 边界（明示）

- 第三方镜像 / CDN 可用性会漂移：本 Skill 的处理是"并发探活 + 换源 + 冷却重试 + 如实报告"，不承诺某条源永远可用。
- `cdn` 只读单文件，不替代 git；分支引用有缓存滞后，正式判定请用 tag/commit 固定。
- `hosts` 只动自己的标记块（`# github-web-skill Start/End`），删除该块即恢复原状；未通过存活校验的 IP 不会写入。

## 许可

MIT（见 `LICENSE`）。
