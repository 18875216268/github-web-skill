# 通道与场景路由（自动生成：改 routes/routes.json 后跑 gh.py routes --render）

> 说明：只讲每条通道「适合什么 / 作用是什么 / 前提与副作用」；不做性能评比。
> 每条通道的**内部降级链**（源池/择路/超时）见其通道目录 README：`channels/<通道名>/README.md`。

## 通道

| 通道 | 经第三方 | 需授权 | 消费供给 | 作用 | 实现与说明 |
| --- | --- | --- | --- | --- | --- |
| `direct` | 否 | 否 | — | 默认首选：走官方端点与官方协议（git 元数据/整仓/推送、raw/api/codeload）。不改源、不改系统。 | `channels/direct/channel_direct.py`（README 含内部降级链） |
| `cdn` | media-cdn | 否 | `cdn` | 只读单个文件：从媒体 CDN 边缘缓存取（并发探活择优；源池只增不删、失败只冷却）。 | `channels/cdn/channel_cdn.py`（README 含内部降级链） |
| `pin` | 否 | 否 | `ip` | 治解析污染与线路劣化：资源层供给 IP 候选（多源聚合+统一测速），单次调用内本地代理钉住；不改系统、进程结束即失效。 | `channels/pin/channel_pin.py`（README 含内部降级链） |
| `hosts` | 否 | 是 | `ip` | 兜底修系统解析（含浏览器）：标记块写入 hosts，需显式授权且必须可回滚。 | `channels/hosts/channel_hosts.py`（README 含内部降级链） |
| `mirror` | mirror-pool | 否 | `mirror` | 只读兜底：直连与钉 IP 都失败时经第三方转发代理读取（写操作永不经过；并发探活择优、源池只增不删）。 | `channels/mirror/channel_mirror.py`（README 含内部降级链） |
| `offline` | 否 | 否 | — | 不联网的约定态（无实现文件）：链尾如实报告失败原因并给出下一步建议，不含任何离线预置数据。 | 约定态（无实现文件） |

## 场景路由（情况 × 通道矩阵）

> 情况决定通道序列；通道内部还有各自的源级降级链（见各通道目录 README）。

| 情况（场景） | 说明 | 通道降级链 | 入口命令 |
| --- | --- | --- | --- |
| `file_read` | 取单个文件内容（manifest / README / 小文件） | `cdn` → `direct` → `pin` → `mirror` | gh.py get <owner>/<repo>:<path> 或 --url |
| `git_read` | git 只读（ls-remote / fetch / pull / clone） | `direct` → `pin` → `mirror` | gh.py git <只读子命令> |
| `git_write` | git 写（push / tag / 提交相关） | `direct` → `pin` | gh.py git <写子命令> |
| `resolve_broken` | 解析失败或连接劣化（DNS 被污染、连接被重置） | `pin` → `hosts` → `mirror` | gh.py get / git（pin 为其一环）；hosts 需授权 |
| `human_access` | 人打不开 GitHub（浏览器场景） | `hosts` | gh.py hosts --status / --apply --yes / --rollback |
| `all_failed` | 全部通道失败（含 git clone 全链失败——只需代码时 next 给 codeload 归档建议） | `offline` | （无命令：如实告知 + 离线指引） |

## 红线

- mirror 永不用于写操作：git_write 链中不得出现 mirror（验收用例锁定）
- hosts 需要显式 --yes 授权；apply 必留备份，rollback 必须能恢复
- shallow（--depth 1）对 git 只读默认生效——它是传输量乘数，不是通道
- 取用类命令（get/git）每次调用都报告：命中通道 / 是否经第三方 / 失败原因 / 下一步建议（独立命令 hosts/routes/update/diag 按各自语义输出）
- 失败 ≠ 失效：源不因一次不可达被删除——只按指数退避冷却（≤1h），到期自动半开重试
- 并发择优：镜像/CDN/IP 探活并发执行、完成即用；单条 4s 超时快速判不通并立即换源
- 链裁剪用 --exclude（与 --force 互斥）：只裁剪当前场景链，不改事实源；排除后链空 → 如实失败
