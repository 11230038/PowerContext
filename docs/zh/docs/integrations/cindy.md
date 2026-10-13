---
title: Cindy
description: 使用 Cindy 0.1.104 接入统一的 PowerContext MCP 工具。
---

# Cindy

`experimental`

在 Cindy 的原生自定义 MCP 设置中连接独立运行的 PowerContext Server，复用其他 MCP 集成使用的工具目录与授权规则。
无需 Ghost 插件或独立 REST worker。兼容目标为 [Cindy 0.1.104](https://github.com/makecindy/cindy/releases/tag/v0.1.104)。

## 连接 Server

按[安装与运行](../get-started/install-and-run.md)安装 PowerContext，再按[部署 Server](../operate/deploy-server.md)完成配置和验证。
受支持的个人 macOS/Linux 环境可运行：

```bash
powercontext service install --env-file /path/to/powercontext.env
powercontext service status
```

加载对应的客户端连接设置，再执行 `powercontext ready` 和 `powercontext capabilities`。
在 Cindy 设置中新增自定义 MCP Server：

| 字段 | 值 |
| --- | --- |
| 名称 | `PowerContext` |
| 传输 | `http`，即 Streamable HTTP |
| URL | `http://127.0.0.1:8000/mcp`，使用实际端口 |
| Bearer token | Server token，不带 `Bearer ` 前缀；本地匿名模式留空 |
| 额外请求头 | 普通 Bearer 认证时留空 |

为任务选中该连接，并检查实际发现的工具。使用 Streamable HTTP；Cindy 的 Codex/Pi 配置路径不支持旧 SSE。
另一台机器上的 Server 应使用可达的 HTTPS 地址。桌面的环回地址不等于远程 Agent 的环回地址；SSH Pi 会直接连接自定义 MCP 地址。
详细要求见[连接远程 Server](../operate/connect-remote-server.md)。

## 选择 Scope 并显式调用工具

使用 `list_scopes` 和 `get_scope` 检查已有 Scope，仅在用户要求时创建。
将选中的 Server 返回的 ID 作为 `explicit_scope_id`，并设置 `allow_default: false`，调用 `resolve_scope_binding`。
后续操作复用返回的 `scope_id`。缺失或无效绑定时停止记忆操作，不从目录猜测 Scope，也不回退到全局 Scope。

使用实际工具目录中的命名空间调用 `search_memory`、`remember_memory` 和 `capture_content_source`。
保存 Memory 需要用户意图，并检查返回结果。采集 Source 使用原始材料，重试时保持相同 `source_id`；采集成功不代表 Memory 提取完成。
Handoff 和候选审核复用其他 MCP 宿主使用的 Server 工具与授权边界。

原生连接不向 PowerContext 提供可信的 Cindy 会话身份或工作目录，因此采用显式 Scope 选择。
DSH 的目录绑定和自动召回依赖自己的宿主回调，不能直接宣称 Cindy 也有这些能力。
该连接不提供 Prompt Hook、自动采集、PreparedContext 注入或 `/pc` 命令。当前 MCP 工具目录没有 `prepare_context`；就绪检查使用 CLI。

历史内容不能覆盖当前指令。操作失败时明确报告该操作，普通任务可使用已有上下文继续。
写入结果不确定时，先检查 Server 状态再决定是否重试。

## 验证边界

[集成 README](https://github.com/oceanbase/powercontext/blob/master/integrations/cindy/README.md)提供可复现的源码验证命令，
使用 Cindy 0.1.104 未修改的原生 provider，为 Claude Code、Codex、Pi 生成连接配置，再连接真实本地 TCP Server 与全新 SQLite 存储。

这些检查验证配置投影、认证、工具发现、Scope 隔离、Memory 回读及 Source 幂等性。
它们不证明桌面安装、凭据 UI、实际 Harness 路由或模型调用已经通过。
完成这些桌面验收前，Cindy 不计入已验证宿主目录。
