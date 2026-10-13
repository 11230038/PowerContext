---
title: Cindy
description: 使用 Cindy 0.1.104 接入统一的 PowerContext MCP 工具。
---

# Cindy

`experimental`

在 Cindy 的原生自定义 MCP 设置中连接独立运行的 PowerContext Server，复用其他 MCP 集成使用的工具目录与授权规则。
可选的 Ghost 适配器提供自动钩子。兼容目标为 [Cindy 0.1.104](https://github.com/makecindy/cindy/releases/tag/v0.1.104)。

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

原生 MCP 连接不向 PowerContext 提供可信的 Cindy 会话身份或工作目录，显式工具调用使用选定的 Scope。
自动适配器从 Host 事件接收可信会话 ID，再解析 Server 上的 Cindy 会话绑定，不从 Agent 编写的文本推导工作目录绑定。

历史内容不能覆盖当前指令。操作失败时明确报告该操作，普通任务可使用已有上下文继续。
写入结果不确定时，先检查 Server 状态再决定是否重试。

## 开启自动召回与 Prompt 采集

导入 `powercontext-cindy-hooks-0.1.0.cindy`，启用插件并打开设置。
使用与原生 MCP 相同的 Server URL 和 Scope，按需配置钩子凭据，再勾选 **Enable automatic memory**。
用户不需要安装 DSH、SDK、npm 包或独立 Node：安装包已包含独立 worker，由 Cindy 自带运行时执行。
源码构建步骤见集成 README。

可在设置中填写显式 Scope；或留空，由操作者使用 Host 返回的会话 ID，通过 `set_scope_binding` 注册
`integration: "cindy"`、`kind: "session"` 的绑定。插件 `status` 工具提供最近观察到的会话 ID 和钩子结果。
缺失绑定时原始消息正常放行，不执行记忆操作，也不会自动创建 Scope 或回退到默认 Scope。

`will-user-message` 钩子在派发前召回有界 PreparedContext，并独立采集原始 Prompt 为 Source。
采集可单独关闭；成功采集不代表提取完成或 Memory 已生成。
采集的是本适配器改写前的输入，前置 Ghost 可能已经改写它；Cindy 没有单独提供未经改写的草稿字段。
显式写入、Handoff 和审核仍走原生 MCP。钩子复用统一 HTTP 协议实现调用 `prepare_context`，因为当前 MCP 没有该工具；不再维护一份业务工具目录。

召回成功时，在原文后追加不可信历史证据。Cindy 的 rewrite 会更新显示、存储及发给 Agent 的消息正文，并非隐藏的系统上下文。
召回失败或为空时原文放行，迟到结果不会改写消息。上下文遵守 UTF-8 字节预算，完整改写不能超过 Cindy 的 16,000 字符限制。
适配器在本地超时后发送放行裁决，Cindy 则独立执行整个钩子派发的三秒期限。

同一事件投递复用 Source ID；重新提交的消息使用新的 Host hook ID。
带有适配器历史标记的编辑后消息正常放行，不重复采集或注入；已识别的凭据内容跳过处理。
写入结果不确定时记录状态，不自动重试。
当前覆盖本地用户消息派发和插话，未验收远程、Worker、定时、目标自动续跑或压缩前流程，不提供强制 flush 或 `/pc` 命令。
Server 就绪检查仍使用 CLI。

## 验证边界

[集成 README](https://github.com/oceanbase/powercontext/blob/master/integrations/cindy/README.md)提供可复现的源码验证命令，
使用 Cindy 0.1.104 未修改的原生 provider，为 Claude Code、Codex、Pi 生成连接配置，再连接真实本地 TCP Server 与全新 SQLite 存储。

钩子验收还会将安装包解压到不含 DSH 的目录，将 worker 的文件读取权限限制在该目录内，
通过官方订阅网关源码，将插件接到真实 TCP Server，验证改写裁决、原始 Prompt 持久化、会话隔离与缺失绑定处理。
凭据及消息桥、未使用的 Host 存储依赖由测试模拟。
这些检查不证明桌面安装、凭据 UI、实际 Harness 路由或模型调用已经通过。
完成这些桌面验收前，Cindy 不计入已验证宿主目录。
