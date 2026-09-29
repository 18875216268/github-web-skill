# update/ · 更新层

**触发语义（最重要）**：本技能**从不自检更新**——无后台线程、无定时器，`diag` / `get` / `git` / `routes` 等任何其他命令都**不附带**版本检查。只有调用方（Agent 或人）**显式执行** `gh.py update ...` 时才出网。

## 更新地址

<https://github.com/18875216268/github-web-skill>（远端 `main` 分支的 `manifest.json` 为版本事实源）

## 命令

| 命令 | 出网 | 授权 | 作用 |
| --- | --- | --- | --- |
| `gh.py update --check` | 是（只读） | 免 | 拉远端 manifest.json 比版本；报告 `local / remote / update_available` |
| `gh.py update --apply --yes` | 是 | **显式 --yes** | 下载 codeload 归档 → staging 校验 → 备份 → 原地应用 |
| `gh.py update --rollback` | 否 | 免 | 从最近一次更新前的备份恢复 |
| 通用：`--ref <分支/标签>` | | | 默认 `main`；`--deadline <秒>` 限总耗时 |

## 流程与安全边界

1. **检测**：直取远端 `manifest.json`（raw 域，URL 构造见 `update.py` 的 `raw_manifest_url()`）。
   链固定 `direct → pin → mirror`——**故意不含 cdn**：更新检测要求新鲜度，不走有缓存的第三方 CDN。
2. **下载**：`codeload.github.com/<repo>/zip/refs/heads/<ref>`（zip 快照，普通 HTTP 可取），同链降级。
3. **staging 校验**（任一不过即拒绝，**不触碰现有包**）：zip 路径穿越防护（拒绝绝对路径与 `..`）→ 解压到用户区暂存目录 → 必须存在 `manifest.json` → `manifest.name` 必须是 `github-web-skill`（防错包）。
4. **备份**：当前包整体复制到 `~/.github-access/update/backup/<时间戳>/`。
5. **原地应用**：新文件覆盖 + 包内多余文件删除 + 空目录清理；更新档案（`from / to / backup / ref`）落用户区 `update/` 目录，`update --rollback` 读取。
6. **回滚**：优先按更新档案记录的备份恢复；否则取最新时间戳备份。

**写入范围**：运行态零写入包内（日志/缓存/备份全部在用户区 `~/.github-access/`）；唯一例外是 `--apply`——显式授权替换包文件本身，且必先备份、必可回滚。

## 实现说明

- `update.py` 为**纯逻辑**模块（版本比较 / staging 校验 / 备份 / 应用 / 回滚），可离线单测；
  出网动作由 `gh.py cmd_update` 经**自有通道链**完成（本技能吃自己的狗粮：更新本身也走降级链）。
- 版本比较：逐段数字、位数不齐补零、非数字段容错——比较永不抛异常。

## 已知边界

- raw 有分钟级缓存滞后：刚发布的版本可能短暂检测不到——需要强新鲜度时用 `--ref <tag>` 固定。
- `--apply` 过程中包文件被替换；**正在运行的本进程不受影响**（模块已加载进内存），下次调用即新版本。
- 回滚是「最近一次更新」粒度；多次更新产生多个备份目录（`~/.github-access/update/backup/`），可手动清理。
