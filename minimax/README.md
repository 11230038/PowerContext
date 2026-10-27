# 规有所依：面向软件持续演进的 SDD 上下文管理系统

本目录是 MiniMax × OceanBase 赛题的提交材料。作品实现了一个规格驱动开发（SDD）上下文模块：

- 把规格、代码和测试导入 **seekdb**，建立可检索索引；
- 根据开发任务输出**当前有效**的规格条目、代码文件/符号和测试来源；
- 把任务进展写入 **PowerContext**，模块重启后在新进程中读取并继续使用；
- 由 **MiniMax** 基于该上下文完成一次真实代码修改，修改前后用同一组测试验证。

业务工程是 `app/` 下的 `loanboard` 借阅列表服务，修改任务是实现 `SPEC-LOAN-004` 逾期筛选。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/` | 业务工程：可运行代码、规格、目标测试与回归测试 |
| `sdd_context/` | 上下文模块：seekdb 索引、检索、PowerContext 状态、MiniMax 调用、CLI |
| `samples/task.md` | 验证样例的任务描述 |
| `samples/expected_context.json` | 上下文中必须出现的来源清单 |
| `samples/snapshots/before/`、`after/` | 修改前后代码快照 |
| `samples/diffs/overdue_filter.diff` | 提交代码对应的统一差异 |
| `samples/specs/loans_v2.md` | 用于验证“规格更新后重新导入”的 v2 规格 |
| `samples/run_validation.py` | 一键复现全部验收步骤 |
| `artifacts/minimax/` | MiniMax 实际调用记录（请求上下文、响应、usage、模型版本） |
| `artifacts/context/` | 模块实际输出的上下文 JSON |
| `artifacts/logs/` | 测试与验证日志、seekdb 查询证据 |
| `artifacts/state/` | PowerContext 状态指针与重启后读取到的状态 |

## 环境与依赖

- Python 3.12
- [PowerContext](https://pypi.org/project/powercontext/) `1.4.1`（`builtin` 扩展，用于任务状态）
- PyMySQL `>=1.2`（连接 seekdb 的 MySQL 协议端口）
- pytest `>=8,<10`
- seekdb `1.4.0.0`（OceanBase 兼容；官方镜像 `oceanbase/seekdb:latest`）
- MiniMax Chat Completions API，模型 `MiniMax-M3`（中国区 `https://api.minimaxi.com/v1`）

安装：

```bash
cd minimax
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

启动 seekdb（已有实例时跳过）：

```bash
docker run -d --name seekdb -p 2881:2881 oceanbase/seekdb:latest
```

默认连接 `127.0.0.1:2881`、用户 `root`、空密码。可通过 `SEEKDB_HOST`、`SEEKDB_PORT`、`SEEKDB_USER`、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE` 覆盖。

MiniMax 凭据只从环境变量读取，不写入仓库：

```bash
export MINIMAX_API_KEY=...          # 必填，仅用于 ask-minimax
export MINIMAX_BASE_URL=https://api.minimaxi.com/v1   # 默认值
export MINIMAX_MODEL=MiniMax-M3                        # 默认值
```

PowerContext 状态库默认在 `minimax/.state/powercontext.db`，可用 `POWERCONTEXT_STATE_DB` 指定。

## 调用入口

所有命令在 `minimax/` 目录执行。

```bash
# 1. 建库建表
python -m sdd_context init

# 2. 导入规格、代码、测试（重建 seekdb 索引）
python -m sdd_context ingest --root app --label app

# 3. 根据任务构造开发上下文（标准输出 + 可选 --out 文件）
python -m sdd_context context \
  --task samples/task.md \
  --task-id TASK-OVERDUE-FILTER \
  --label app \
  --out artifacts/context/initial.json

# 4. 记录任务进展到 PowerContext
python -m sdd_context record \
  --task-id TASK-OVERDUE-FILTER \
  --done "实现 SPEC-LOAN-004" \
  --todo "提交材料" \
  --verification "target tests exit=0"

# 5. 新进程读取状态（模块重启后复用）
python -m sdd_context status --task-id TASK-OVERDUE-FILTER

# 6. 把上下文发给 MiniMax，生成修改后的完整文件
python -m sdd_context ask-minimax \
  --task samples/task.md \
  --context artifacts/context/initial.json \
  --target samples/snapshots/before/service.py \
  --out runs/minimax/service.py \
  --task-id TASK-OVERDUE-FILTER
```

`context` 的输出字段：

- `specs[]`：规格编号、标题、来源 `app/specs/loans.md#SPEC-...` 和当前生效内容；
- `code[]`：代码文件路径与符号（如 `app/loanboard/service.py#LoanService.list_loans`）；
- `tests[]`：测试文件与测试函数来源；
- `state`：PowerContext 中的已完成事项、待办事项、验证结果和 Artifact ID；
- `database`：seekdb 文档数、命中 posting 数、查询词和 `query_log` 记录 ID。

## 验证样例

### 任务与有效规格

任务见 `samples/task.md`：为 `loanboard` 实现逾期筛选。必须包含的上下文来源见 `samples/expected_context.json`，核心是：

- `SPEC-LOAN-004`（逾期筛选）
- `SPEC-LOAN-006`（兼容性）
- `app/loanboard/service.py#LoanService.list_loans`
- `app/tests/test_loans_overdue.py` 中的目标测试

### 初始数据

`app/` 自带 5 条内存借阅数据（`loanboard/cli.py`），测试使用固定日期，不依赖系统时钟。规格 v1 位于 `app/specs/loans.md`。

### 操作步骤与预期结果

```bash
python samples/run_validation.py
```

脚本从干净状态开始，依次执行并记录：

1. 删除 `.state` 状态库，重建 seekdb 索引（35 个文档：6 规格 / 12 代码 / 17 测试）；
2. 用 `samples/snapshots/before/service.py` 覆盖工作副本，目标测试 **6 failed, 1 passed**，回归测试 **15 passed**（失败是断言失败，不是依赖或导入错误）；
3. 应用 `samples/diffs/overdue_filter.diff`，目标测试 **7 passed**，回归测试 **15 passed**；
4. 构造上下文，校验必要来源存在；
5. 写入 PowerContext，再启动**新进程**读取 `done/todo/verifications` 与 Artifact ID；
6. 用 `samples/specs/loans_v2.md` 覆盖规格并重新导入，上下文出现 v2 的“严格早于 / 不含到期当天”，随后恢复 v1。

预期最后一行为 `18/18 checks passed`。完整命令、退出码和输出保存在 `artifacts/logs/validation-*.json`。

### 重置

```bash
rm -rf .state runs
python -m sdd_context ingest --root app --label app
```

删除 seekdb 数据库可执行 `DROP DATABASE sdd_context;`，然后重新 `init` 与 `ingest`。

## MiniMax 使用

- 接入方式：HTTPS Chat Completions API（`/v1/chat/completions`），无 SDK 依赖。
- 模型：`MiniMax-M3`；请求包含任务、检索到的规格/代码/测试来源、目标文件原文。
- 记录：`artifacts/minimax/` 保存每次请求的模型、usage、延迟、完整消息与实际响应（已去除 `<think>` 推理段，不提交私有思维链）。
- 迭代：第一次输出功能正确但保留了“尚未实现”的旧文档字符串；第二次在提示中要求同步更新文档字符串，其产物已作为 `app/loanboard/service.py` 提交。两次记录都保留，最终差异与 `samples/diffs/overdue_filter.diff` 一致。

## seekdb 使用

- 表：`docs`（35 个规格/代码/测试文档）、`terms`（词项 posting）、`ingest_runs`、`query_log`。
- `ingest` 写入文档与倒排 posting；`context` 通过 `SELECT ... FROM terms WHERE term IN (...)` 取 posting，在应用层做 IDF 排序，并把本次查询写入 `query_log`。
- 证据：`artifacts/logs/seekdb-evidence.json` 记录引擎版本、表行数、最近入库与查询记录；上下文 JSON 的 `database.query_log_id` 可回查。

## PowerContext 使用

- 模块通过 `powercontext.builtin.runtime` 打开 SQLite 内置运行时，使用 Atomic Memory 保存 `sdd-task-state`（JSON：`done/todo/verifications/task_hash`）。
- 指针文件 `.state/state-pointer.json` 只保存 Artifact ID；状态正文在 PowerContext 中。重启后 `status` 通过 Artifact ID 读取，读取失败时回退到 PowerContext 检索。
- 证据：`artifacts/state/status.json`、`artifacts/state/pointer.json`，以及验证日志中的 record/status 两次独立进程记录。

## 已知限制

- 需要可用的 seekdb 实例；未做多实例或并发写入压测。
- 检索是词项索引 + IDF 排序，面向中小型工程仓库；未引入向量检索。
- `ask-minimax` 需要网络与有效 `MINIMAX_API_KEY`；中国区与国际区 base URL 不同，可用 `MINIMAX_BASE_URL` 切换。
- Windows 控制台默认编码可能影响中文显示，CLI 已将标准输出固定为 UTF-8；验证脚本优先使用 GNU `patch`，缺失时回退到 `git apply --directory`。
- 状态库是本机 SQLite 文件，不作为多用户共享存储。

## 复用与许可

业务工程、上下文模块和验证样例均为本次提交新写代码，未复制第三方源码或数据。依赖库遵循各自许可证；MiniMax、seekdb、PowerContext 的使用方式见上。
