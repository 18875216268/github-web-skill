# 通道 ssh：SSH 传输官方端点探测

> 单开源类 `kinds.ssh`（仅本通道消费）；**不进自动降级链**；零凭证。

## 这扇门是什么

GitHub 有两扇独立的大门。本技能其余通道（direct/pin/mirror/cdn）全走 **HTTPS 门**（443，
TLS 握手会明文暴露"我在访问 github.com"——被针对性识别的软肋）。本通道管的是**第二扇门**：

| | HTTPS 门 | SSH 门 |
|---|---|---|
| 端口 | 443 | **22**（官方备门 `ssh.github.com:443`） |
| 协议 | TLS（有 SNI） | SSH（**无 SNI**——握手里没有域名可查） |
| 覆盖操作 | 全部 | 仅 git 联网操作（clone/fetch/pull/push/ls-remote/submodule update 等——raw/Release/网页不走 SSH） |

价值：**独立端口 + 无 SNI**，是 HTTPS 被针对性阻断时的逃生族；对写操作尤其重要
（`git_write` 链只有 `direct→pin` 两条 HTTPS 路，SSH 是红线之外唯一合法的第三条）。

## 双模语义（凭证问题一次说清）

| 模式 | 凭证 | 行为 |
|---|---|---|
| **探测**（`gh.py ssh --status`） | **零凭证** | 纯 TCP 连通性：两扇门开没开、延迟多少。无 GitHub 账号也能跑 |
| **使用**（git 走 SSH） | 用户自己的 key | 用户自行生成 key、公钥贴到 GitHub、用 SSH 地址——git/ssh 进程直接使用用户自己的 agent，**本技能零接触** |

## 官方端点（来源 `sources.json` 的 `kinds.ssh`，单开）

| 端点 | 地址 | 说明 |
|---|---|---|
| `github-22` | `github.com:22` | SSH 标准门 |
| `ssh-over-443` | `ssh.github.com:443` | 官方备门：22 被封时走 443 端口承载 SSH |

## 不做什么（边界即设计）

- **不进自动降级链**：SSH 只承载 git 操作，不能替 HTTPS URL 取 raw/release——进链是伪需求
- **不改道**：传输方式由用户给的地址决定（HTTPS 地址 → HTTPS 链；SSH 地址 → SSH 传输），
  技能绝不擅自改道；需要改道时经 `--transport ssh`（调用级改写，不碰 remote 配置），由用户决定
- **不碰凭证**：不生成、不读取、不存储、不传递 key；首次连接的主机指纹确认由用户在自己机器上完成
- **不与 ip 源类混用**：`ssh.github.com` 不进 42 域表——本通道的端点数据在独立的 `kinds.ssh`
