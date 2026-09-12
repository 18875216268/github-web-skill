# 通道与场景路由（自动生成：改 routes/routes.json 后跑 gh.py routes --render）

> 说明：只讲每条通道「适合什么 / 作用是什么 / 前提与副作用」；不做性能评比。

## 通道

| 通道 | 经第三方 | 需授权 | 作用 |
| --- | --- | --- | --- |
| `direct` | 否 | 否 | 默认首选：走官方端点与官方协议（git 元数据/整仓/推送、raw/api/codeload）。不改源、不改系统。 |
| `cdn` | media-cdn | 否 | 只读单个文件：从媒体 CDN 边缘缓存取（并发探活择优；源池只增不删、失败只冷却）。 |
| `pin` | 否 | 否 | 治解析污染与线路劣化：云函数/DoH 取可达 IP，单次调用内本地代理钉住；不改系统、进程结束即失效。 |
| `hosts` | 否 | 是 | 兜底修系统解析（含浏览器）：标记块写入 hosts，需显式授权且必须可回滚。 |
| `mirror` | mirror-pool | 否 | 只读兜底：直连与钉 IP 都失败时经第三方转发代理读取（写操作永不经过；并发探活择优、源池只增不删）。 |
| `offline` | 否 | 否 | 不联网：给出离线预置与人工指引。 |

## 场景路由

| 场景 | 说明 | 降级链 | 入口命令 |
| --- | --- | --- | --- |
| `file_read` | 取单个文件内容（manifest / README / 小文件） | `cdn` → `direct` → `pin` → `mirror` | gh.py get <owner>/<repo>:<path> 或 --url |
| `git_read` | git 只读（ls-remote / fetch / pull / clone） | `direct` → `pin` → `mirror` | gh.py git <只读子命令> |
| `git_write` | git 写（push / tag / 提交相关） | `direct` → `pin` | gh.py git <写子命令> |
| `resolve_broken` | 解析失败或连接劣化（DNS 被污染、连接被重置） | `pin` → `hosts` → `mirror` | gh.py get / git（pin 为其一环）；hosts 需授权 |
| `human_access` | 人打不开 GitHub（浏览器场景） | `hosts` | gh.py hosts --status / --apply --yes / --rollback |
| `all_failed` | 全部通道失败 | `offline` | （无命令：如实告知 + 离线指引） |

## 红线

- mirror 永不用于写操作：git_write 链中不得出现 mirror（验收用例锁定）
- hosts 需要显式 --yes 授权；apply 必留备份，rollback 必须能恢复
- shallow（--depth 1）对 git 只读默认生效——它是传输量乘数，不是通道
- 每次调用都必须报告：命中通道 / 是否经第三方 / 失败原因 / 下一步建议
- 失败 ≠ 失效：源不因一次不可达被删除——只按指数退避冷却（≤1h），到期自动半开重试
- 并发择优：镜像/CDN/IP 探活并发执行、完成即用；单条 4s 超时快速判不通并立即换源
