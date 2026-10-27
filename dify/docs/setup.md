# 部署与排错细节

这份文档是本机实测时的完整步骤，包含 Dify 1.9.2 的几个坑。
命令里的 Key、密码一律用占位符，不要提交真实值。

## 1. 组件与版本

| 组件 | 版本 |
| --- | --- |
| Dify | 1.9.2（docker compose 官方部署） |
| seekdb | `oceanbase/seekdb:latest`（实测 `5.7.25-OceanBase seekdb-v1.4.0.0`，MySQL 协议 2881） |
| PowerContext | `powercontext[builtin]==1.4.1` |
| 模型 | MiniMax-M3，OpenAI 兼容接口 `https://api.minimaxi.com/v1` |

## 2. seekdb

```bash
docker run -d --name seekdb -p 2881:2881 -p 2886:2886 oceanbase/seekdb:latest
```

后端启动时会自动执行 `CREATE DATABASE IF NOT EXISTS tavern`、建三张表并灌入 16 张传闻卡：

* `lore_cards`：卡片本体（`card_id / title / content / tags / weight`）
* `lore_query_log`：每次提问的检索记录（含命中的卡片）
* `turn_log`：每轮对话的行为与回答，关联 PowerContext 工件 id

## 3. 酒馆后端

```bash
cd dify/app
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn server:app --host 0.0.0.0 --port 8090
```

`.env` 里只需要改需要改的：`SEEKDB_HOST/PORT/USER/PASSWORD`、`TAVERN_DB`、
`TAVERN_STATE_DB`（PowerContext 的 SQLite 文件，默认 `../.state/tavern-powercontext.db`）。

接口一览：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | seekdb 版本、卡片数、查询数 |
| GET | `/lore?q=&player_id=&session_id=` | 检索传闻，写 `lore_query_log` |
| GET | `/memory/{player_id}` | 读 PowerContext 记忆（含 `memory_text`、`affinity`） |
| POST | `/memory/{player_id}` | 追加一条行为，写 `turn_log` |
| GET | `/debug/state/{player_id}` | 记忆 + 最近轮次 + 最近检索（验证用） |
| POST | `/debug/reset/{player_id}` | 追加一条空记忆工件，等于「忘掉这个玩家」 |

## 4. Dify 起服务

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

打开 `http://localhost:8080`，按引导创建管理员。
随后用 `POST /console/api/setup` 的返回确认 `step == "finished"`。

## 5. 装模型插件

在 Console 的「插件」页搜索 **OpenAI-API-compatible** 并安装，或者直接调 Console API：

```bash
# 登录拿 cookie 与 csrf_token
curl -c cookies.txt -H "Content-Type: application/json" \
  -d '{"email":"<ADMIN_EMAIL>","password":"<ADMIN_PASSWORD>","language":"zh-Hans","remember_me":true}' \
  http://localhost:8080/console/api/login

CSRF=$(awk '/csrf_token/{print $7}' cookies.txt)

curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
  -d '{"plugin_unique_identifiers":["langgenius/openai_api_compatible:0.0.73@4cf123ffaa4556f079bed6c47f3a462cc825504b859b183239e74eb19136a4b5"]}' \
  http://localhost:8080/console/api/workspaces/current/plugin/install/marketplace
```

安装是异步任务，用返回的 `task_id` 轮询：

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  "http://localhost:8080/console/api/workspaces/current/plugin/tasks/<TASK_ID>"
```

插件装好后，`GET /console/api/workspaces/current/plugin/list` 里能看到
`langgenius/openai_api_compatible`。

## 6. 配 MiniMax-M3

`openai_api_compatible` 是 `customizable-model` 类型的插件，**没有 provider 级凭据**，
要按模型逐个添加（用 provider 级接口会报 `does not have provider_credential_schema`）：

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
  -d '{"model":"MiniMax-M3","model_type":"llm","credentials":{
        "display_name":"MiniMax-M3",
        "api_key":"<MINIMAX_API_KEY>",
        "endpoint_url":"https://api.minimaxi.com/v1",
        "mode":"chat",
        "context_size":"32768",
        "max_tokens_to_sample":"4096",
        "function_calling_type":"tool_call",
        "stream_function_calling":"supported",
        "vision_support":"no_support",
        "structured_output_support":"not_supported",
        "stream_include_usage":"disabled"}}' \
  http://localhost:8080/console/api/workspaces/current/model-providers/langgenius/openai_api_compatible/openai_api_compatible/models/credentials
```

字段名以 `GET .../model-providers` 返回的 `model_credential_schema` 为准；
`vision_support` 的取值是 `support` / `no_support`（不是 `supported`），
`stream_include_usage` 是 `enabled` / `disabled`——填错会 400。

验证：

```bash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  http://localhost:8080/console/api/workspaces/current/models/model-types/llm
# 应看到 MiniMax-M3，status = active
```

## 7. 导入 DSL

Console →「导入 DSL」→ 选 `dsl/cat-tavern.dsl.yml` → 打开应用 →「发布」。
导入后给应用创建 API Key（「API 访问」页），验证脚本用它调 `/v1/chat-messages`。

如果改了流程要重新导入，可以用 Console API：

```bash
# 1) 取当前草稿 hash
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  http://localhost:8080/console/api/apps/$APP_ID/workflows/draft
# 2) 保存草稿：body 里带上一步拿到的 hash，否则报 draft_workflow_not_sync
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
  -X POST --data-binary @draft.json \
  http://localhost:8080/console/api/apps/$APP_ID/workflows/draft
# 3) 发布
curl -b cookies.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
  -d '{"marked_name":"v2","marked_comment":""}' \
  http://localhost:8080/console/api/apps/$APP_ID/workflows/publish
```

## 8. 实测踩到的坑

**Docker 注入的 HTTP 代理会打断容器间调用。**
Docker Desktop 会把宿主代理（如 `http://127.0.0.1:7897`）注入容器，导致 Dify 访问
`plugin_daemon`/`db` 走到代理上直接失败（`Failed to request plugin daemon`）。
解决：给 `api/worker/worker_beat/plugin_daemon/web` 加一份 override，把代理变量清空并把内部服务加进 `NO_PROXY`：

```yaml
services:
  api:
    environment: &no_proxy
      HTTP_PROXY: ""
      HTTPS_PROXY: ""
      http_proxy: ""
      https_proxy: ""
      NO_PROXY: localhost,127.0.0.1,::1,plugin_daemon,api,web,db,redis,nginx,sandbox,ssrf_proxy
      no_proxy: localhost,127.0.0.1,::1,plugin_daemon,api,web,db,redis,nginx,sandbox,ssrf_proxy
  worker:
    environment: *no_proxy
  worker_beat:
    environment: *no_proxy
  plugin_daemon:
    environment: *no_proxy
  web:
    environment: *no_proxy
```

**代码节点 401。** `api` 的 `CODE_EXECUTION_API_KEY` 和 `sandbox` 的 `SANDBOX_API_KEY`
是两处配置，默认值不一样就会 `got status code 401`。把两者改成同一个值后重启 `api`/`worker`。
改了 compose 环境变量后记得再 `docker compose restart nginx`，否则 nginx 还指向上一个 api 容器 IP，页面 502。

**首次启动顺序。** `plugin_daemon` 可能在 `db` 还没起来时 panic 重启；
`docker compose ps` 里看到 `Restarting` 不用管，等 `db` healthy 后它会自己起来。

**HTTP 节点走 ssrf_proxy。** Dify 的 HTTP 请求默认经 `http://ssrf_proxy:3128` 出网，
所以后端必须让 `ssrf_proxy` 也能访问；`host.docker.internal:8090` 在 Docker Desktop 下可用。
Linux 上给 `ssrf_proxy` 和 `api/worker` 都补上 `extra_hosts: ["host.docker.internal:host-gateway"]`。

## 9. 保密

* `.env`、`.state/`、`logs/` 不进仓库。
* DSL 用 `include_secret=false` 导出，只有 provider 名与模型名，没有 Key。
* `docs/`、`README.md`、`samples/` 里出现的 Key/密码全部是占位符。
