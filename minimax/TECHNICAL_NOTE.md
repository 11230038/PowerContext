# 技术说明（一页）

## 目标与结构

任务要求 AI 开发助手在规格持续演进时，知道“当前该遵守什么、该改哪里、如何验证”，并在任务中断后恢复进度。作品由三部分组成：

```
samples/task.md ──► sdd_context.context ──► context JSON ──► MiniMax ──► 代码修改
                          │   ▲                                        │
                          ▼   │                                        ▼
                    seekdb 索引（规格/代码/测试）                  pytest 目标+回归
                          │
                          ▼
                 PowerContext（done/todo/verifications）
```

`app/` 是可直接运行的 `loanboard` 服务；修改任务是为 `LoanService.list_loans` 增加 `overdue_only` 逾期筛选（`SPEC-LOAN-004`）。

## 上下文选择方式

1. **切分**：规格按 `## SPEC-...` 条款切分；代码按文件、类、方法切分；测试按 `test_*` 函数切分。每个文档保留真实路径与符号，ID 由内容哈希生成。
2. **建索引**：中英文混合分词（ASCII 标识符拆分下划线/驼峰，中文取 bigram），标题权重 ×3、符号 ×2、正文 ×1，写入 seekdb 的 `docs` 与 `terms` 表。
3. **检索**：查询词在 `terms` 表取 posting，按 IDF 与词频打分，再叠加页面类型权重、规格编号精确命中（×4）和符号名命中（×1.8）。
4. **输出**：分别选取规格（必含任务点名的 `SPEC-*`）、代码（按文件去重，偏好符号级 chunk）和测试（偏好目标测试），并回读 `docs.content` 给出规格正文。所有来源都来自数据库，不是固定答案。
5. **规格演进**：重新 `ingest` 后旧文档被替换；验证样例把 v1 换成 v2，同一任务立即输出“严格早于 / 不含到期当天”。

## 三项技术的分工

| 技术 | 承担的作用 | 可核对证据 |
| --- | --- | --- |
| MiniMax（`MiniMax-M3`） | 根据上下文生成完整 `service.py` 修改，第二次迭代修正过时文档字符串 | `artifacts/minimax/*.json`：请求消息、usage、模型、响应 |
| seekdb 1.4.0 | 存储 35 个工程文档与倒排 posting，`context` 查询结果直接构成上下文 | `artifacts/logs/seekdb-evidence.json`、上下文中的 `query_log_id` |
| PowerContext 1.4.1 | Atomic Memory 保存 `done/todo/verifications`，新进程按 Artifact ID 读取 | `artifacts/state/status.json`、`pointer.json`、验证日志 |

## 为什么结果可验证

- **来源真实**：每个来源都是 `app/...` 下的真实文件与符号，`samples/expected_context.json` 列出必含项。
- **修改前真实失败**：before 快照运行目标测试得到 6 failed / 1 passed，回归 15 passed；失败为断言失败，无导入或依赖错误。
- **修改后全绿**：应用 MiniMax 产物对应的 diff 后，目标 7 passed、回归 15 passed。
- **状态可复用**：`record` 在进程 A 写入，`status` 在进程 B 读出同样的 done/todo/verifications。
- **规格更新生效**：v2 重新导入后上下文文本改变，恢复 v1 后再次改变，排除“固定答案”。

## 边界与成本

- seekdb 以单实例 MySQL 协议访问，当前是词项检索，规模上限为中小型仓库；更大仓库可增加分页与字段级索引。
- 每次 `context` 只做一次 posting 查询与一次 `query_log` 写入，延迟主要来自数据库往返；`ask-minimax` 的延迟与 token 成本记录在对应 JSON 中。
- 状态只保证模块重启后可读，不试图恢复完整 Agent 会话，符合题面要求。
