# direct · 直连官方

## 一、方式定义
**什么都不改**：不换源、不换系统、不换入口，直连 GitHub 官方端点与官方协议（git smart HTTP / raw / api / codeload）。实现：`channel_direct.py`。

## 二、适合的情况
所有情况的**第一试**（链首默认）：git 元数据（ls-remote）、整仓 clone/pull/push、raw 单文件、api 调用、codeload 归档、Release 资产。环境健康时它就是终点。

## 三、内部降级链（细粒度）
无子链——官方端点是固定集合：`github.com` / `raw.githubusercontent.com` / `api.github.com` / `codeload.github.com` / `objects.githubusercontent.com` / `release-assets.githubusercontent.com` 等（见 `manifest.json` 白名单）。失败判据：curl 非网络错、git 非 128 类可重试错等（见实现）；内容级校验（200 + 错误页/壳页拦截）不可省。

## 四、前提与副作用 / 红线
无第三方接触内容、无需授权、无系统改动。受 DNS 污染与线路劣化影响——这正是 `pin` 存在的理由。

## 五、实测记录
2026-09-11 真机：健康环境下即成功路径；对"TLS 掐断"类 IP 劣化无解（交给 pin 的传输级 failover）。
