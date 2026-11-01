# Qoder acceptance conversation

Use this short script after adding the PowerContext MCP endpoint to Qoder.

## Turn 1 — save explicit project guidance

> 请通过 PowerContext 记住以下项目规则，供后续会话使用：修改代码前先运行最小目标测试；修改后先跑目标测试，再跑回归测试；除非任务明确要求，否则保持现有 API 兼容；优先做聚焦修改，不为标准库能完成的事情增加依赖。

Expected MCP call: `remember_memory` (one or more Atomic Memory records).

## Turn 2 — start a new Qoder conversation

> 我准备继续这个项目的编码任务。请先从 PowerContext 检索相关记忆，告诉我修改和验证时必须遵守的流程、API 决策和编码约定。

Expected MCP call: `search_memory`.

Expected answer must mention:

- target tests before and after the edit;
- regression tests after target tests;
- API compatibility unless explicitly changed;
- focused edits and avoiding unnecessary dependencies.

## Turn 3 — inspect exact evidence

Ask Qoder to show the returned PowerContext Artifact reference. The response should contain an `atomic-memory` artifact ID and revision rather than a fabricated local note.
