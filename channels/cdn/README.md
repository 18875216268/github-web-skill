# cdn · CDN 缓存

## 一、方式定义
**换内容来源**：从媒体 CDN 的边缘缓存读**单个文件**（源还是 GitHub 仓库，只是读的是 CDN 缓存副本）。实现：`channel_cdn.py`（源池=统一资源层 `sources.json` 的 kinds.cdn 节，与资源层聚合器 `collect.py` 同口径）。

## 二、适合的情况
只读**单个文件**（manifest / README / 小配置）——"取单文件"场景链的**首选**（快）。

## 三、内部降级链（细粒度）
13 源池：jsDelivr 官方四边缘域（主/Fastly/Gcore/Cloudflare 测试）+ bunny 镜像 + 社区公认等价源（Statically / raw.githack / gitmirror-raw / gitcdn）+ **JSDMirror 系 4 域**（腾讯云 EdgeOne：jsdmirror/admincdn/radishzz/sikao123，路径规则与 jsDelivr 完全一致）。
择路：账本热源直取（免探测开销）→ **并发 HEAD 探活完成即用**（最快者先试）→ 其余按账本序兜底。
**内容级校验不可省**：CDN 有"200 + 错误说明文本"的历史，只看状态码会拿错内容。

## 四、前提与副作用 / 红线
只读（不替代 git）；分支引用有**缓存滞后**——正式判定请用 tag/commit 固定。第三方来源，报告标注 `third_party: media-cdn`。

## 五、实测记录
2026-09-11 真机：8 域实测收录；**失败 ≠ 失效**——不可达只按指数退避冷却（封顶 1h、到期自动半开重试），源池只增不删。
