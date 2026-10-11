# PowerContext 记忆体验 Demo

和 AI 助手「小O」聊天，亲身体验 Agent 的长期记忆：告诉它一些关于你的事，
换个会话它还记得；关掉记忆开关它就"失忆"；还可以在面板上让它遗忘或修改某条记忆。

底层是开源项目 [PowerContext](https://github.com/oceanbase/powercontext)——面向 AI Agent
的上下文与记忆持久层。这个 Demo 单进程运行，不用装数据库，几分钟就能在你自己的机器上跑起来。

## 自己部署

需要：一台能联网的 Linux/macOS 机器 + 任一 OpenAI 兼容模型的 API Key
（DashScope / DeepSeek / 本地 vLLM 都可以，聊天和记忆提取共用一个 Key）。

```bash
git clone -b demo-2026 https://github.com/oceanbase/powercontext.git
cd powercontext

# 安装 uv（已有可跳过；uv 会自动准备合适的 Python）
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync --frozen --extra server --extra builtin

cp demo/.env.example demo/.env
# 编辑 demo/.env：填入你的口令和模型 Key

uv run --frozen python -m demo
```

打开 <http://127.0.0.1:8080>，用你设置的口令进入。所有数据落在 `demo/data/`
（SQLite），删掉这个目录就完全重置。

## 跑起来之后，试试这样玩

1. 输入口令和昵称进入（换个昵称就是一个新用户，记忆互相隔离）；
2. 跟小O聊几件你自己的事（口味、爱好、工作……）；
3. 等右侧「我的记忆」浮现出它自动提炼的记忆（通常几秒）；
4. 点「新会话」清空聊天窗，再问"你还记得我是谁吗"——它仍然认识你；
5. 关闭顶部的记忆开关再问同样的问题，对比它的反应；
6. 在面板上「遗忘」或「修改」一条记忆，下一句话立刻生效。

### 配置说明（demo/.env）

`demo/.env.example` 本身就是一份带注释的完整示例，关键项：

| 变量 | 说明 |
|---|---|
| `DEMO_PASSPHRASE` | 进门页口令，自己随便定 |
| `DEMO_PORT` | 监听端口，默认 8080 |
| `DEMO_LLM_BASE_URL` / `_API_KEY` / `_MODEL` | 聊天模型，任何 OpenAI 兼容端点 |
| `DEMO_LLM_EXTRA_BODY` | 可选，合并进聊天请求的额外参数（如 DashScope qwen3 系列关思考：`{"enable_thinking": false}`） |
| `POWERCONTEXT_SERVER_INFERENCE_GENERATION_*` | 记忆自动提取用的模型；**模型名必须用 `openai-chat:` 前缀**（`openai:` 前缀走 Responses API，多数兼容端点不支持） |
| `POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_*` | 可选，向量检索；不配则自动退化为关键词检索 |

### 它是怎么工作的

- **单进程**：FastAPI 页面服务 + 进程内以 loopback 方式运行的真实 PowerContext 服务（SQLite 落盘，重启后记忆不丢）；
- **每人一个记忆空间**：昵称映射到 PowerContext 的 Scope，互不可见；
- **先改写再检索**：每轮先用模型把你的话改写成检索查询（"我养的它叫什么"→"……养的猫名字"），
  把指代展开成实体；搜不到时兜底带上最近的几条记忆，保证身份类问题也能答上来；
- **自动提炼**：每轮对话结束后，由提取模型从对话原文中提炼长期记忆（偏好、事实、约束）；
- **面板即产品 API**：遗忘/修改直接调用 PowerContext 的 retire / revise，实时生效；
- 这个页面只是 PowerContext 的一种用法——它还提供 MCP / CLI / SDK / LangChain 集成，
  任何 Agent 都能把这套记忆能力直接挂上自己。

## 排障

- `uv sync` 报 powercontext-langchain / powercontext 解析冲突（uv 版本相关的已知问题）：
  加 `--frozen` 使用仓库锁文件，上面命令里已带；
- 聊天报「模型调用失败」：检查 `DEMO_LLM_*` 三项与端点连通性（Key、base_url、模型名）；
- 「我的记忆」一直为空：提取模型配置有误——最常见的是 `GENERATION_MODEL` 用了 `openai:`
  前缀（启动日志会打警告）；另外 `GENERATION_HEADERS` 必须是合法 JSON 字符串；
- 机器配了 HTTP_PROXY 且推理端点是本机 127.0.0.1 时提取报 502：`NO_PROXY` 需要写精确 IP
  （CIDR 写法如 `127.0.0.0/8` 不被 httpx 识别）；
- 回归测试（不需要模型）：`uv run --no-sync pytest demo/tests -v`。

## 结构

`demo/app.py` FastAPI 路由与生命周期 · `demo/server.py` 进程内 PowerContext 服务 ·
`demo/agent.py` 聊天编排（改写/召回/生成/提取） · `demo/static/index.html` 单文件前端 ·
`demo/tests/` 回归测试。
