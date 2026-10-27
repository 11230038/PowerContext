# 猫酒馆 Cat Tavern — Dify × OceanBase「Just for Fun」赛题提交

一个真的能玩的文字小游戏：你是酒馆的客人，柜台后面是记性极好的老猫「老白」。
**Dify 负责整条流程编排**，**seekdb 负责酒馆传闻的检索**，**PowerContext 负责玩家的跨会话记忆**——
你在第一场对话里偷吃了鱼干，第二天换个会话再进门，老白仍然记得，而且语气会变。

## 目录

| 路径 | 内容 |
| --- | --- |
| `dsl/cat-tavern.dsl.yml` | 可直接导入 Dify 1.9.2 的 Chatflow DSL（advanced-chat，7 个节点） |
| `app/` | 酒馆后端（FastAPI）：seekdb 读写 + PowerContext 记忆，供 Dify 的 HTTP 节点调用 |
| `samples/validate_cat_tavern.py` | 端到端验证脚本，跑 3 场对话、9 项断言，输出证据 |
| `artifacts/` | 真实运行证据：验证报告、Dify 节点执行轨迹 |
| `docs/setup.md` | 详细的部署步骤（含 Dify 插件安装、模型供应商配置、常见坑） |
| `.state/` | 运行时生成，已被 `.gitignore` 忽略 |

## 玩法与流程

```
玩家 ──> Dify Chatflow
          ├── ① 开始（player_id / session_id）
          ├── ② HTTP GET  /memory/{player_id}   ──> PowerContext Atomic Memory（老白记得的事）
          ├── ③ HTTP GET  /lore?q=...            ──> seekdb（16 张酒馆传闻卡）
          ├── ④ 代码节点：把两份 JSON 拼成上下文
          ├── ⑤ LLM 节点：MiniMax-M3 扮演老白
          ├── ⑥ HTTP POST /memory/{player_id}   ──> 写入这次的行为（append-only）
          └── ⑦ 回答
```

关键点：

* **Dify 是唯一的编排者**：分支、HTTP 调用、上下文拼装、模型调用、写回记忆全部在 Chatflow 里完成，后端只是被调用的服务。
* **seekdb 真的在存与取**：16 张传闻卡（鱼干、井、铃铛、账本、唱片机……）落在 `tavern.lore_cards`；每次提问会按中英文词元做检索并写一条 `lore_query_log`。
* **PowerContext 真的在记**：每轮玩家行为写成一条 Atomic Memory 工件，指针文件落到 `dify/.state/`；同一 `player_id` 换新会话仍能读到，不同 `player_id` 互不可见。

## 运行前提

* Docker（跑 seekdb 与 Dify）
* Python 3.11+（跑酒馆后端和验证脚本）
* 一个 MiniMax API Key（走 OpenAI 兼容接口，`https://api.minimaxi.com/v1`）

## 一、启动 seekdb

```bash
docker run -d --name seekdb \
  -p 2881:2881 -p 2886:2886 \
  oceanbase/seekdb:latest
```

后端第一次启动时会自动建库 `tavern`、建表并写入 16 张传闻卡。

## 二、启动酒馆后端

```bash
cd dify/app
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # 按需改 SEEKDB_PASSWORD 等
uvicorn server:app --host 0.0.0.0 --port 8090
```

自检：

```bash
curl http://127.0.0.1:8090/health
# {"status":"ok","engine_version":"5.7.25-OceanBase seekdb-v1.4.0.0","lore_cards":16,...}

curl "http://127.0.0.1:8090/lore?q=鱼干&player_id=demo&session_id=s1"
```

> Dify 跑在容器里，DSL 里用的是 `http://host.docker.internal:8090`。
> Docker Desktop（Windows/macOS）开箱可用；Linux 上请给 Dify 的 `api`/`worker` 服务加
> `extra_hosts: ["host.docker.internal:host-gateway"]`，或把 DSL 里的地址改成你的宿主地址。

## 三、启动 Dify 并配置模型

```bash
git clone https://github.com/langgenius/dify.git
cd dify/docker && cp .env.example .env && docker compose up -d
# 打开 http://localhost:8080，按提示创建管理员
```

然后（详见 `docs/setup.md`）：

1. 在「插件」里安装 **OpenAI-API-compatible** 模型插件（`langgenius/openai_api_compatible`）。
2. 在「设置 → 模型供应商」里添加模型：
   * 模型名：`MiniMax-M3`
   * API Key：你的 MiniMax Key（**不要提交到仓库**）
   * Base URL：`https://api.minimaxi.com/v1`
   * Context Size：`32768`，Mode：`chat`
3. 「导入 DSL」选择 `dsl/cat-tavern.dsl.yml`，导入后点「发布」。

## 四、开玩

在 Dify 的调试面板里，输入变量：

* `player_id`：比如 `lin`
* `session_id`：比如 `s1`

然后说一句「我把你柜台上的鱼干全偷吃了」。
开一个新对话（`session_id` 改成 `s2`，`player_id` 不变），再问「你还记得我上回干了什么吗」——
老白会提起来，语气也会从「陌生」变成「警惕」。

也可以走服务 API：

```bash
curl -N http://localhost:8080/v1/chat-messages \
  -H "Authorization: Bearer app-你的应用APIKey" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"player_id":"lin","session_id":"s1"},
       "query":"巷口那口井里到底是什么?",
       "response_mode":"streaming","user":"demo"}'
```

## 五、验证

```bash
python samples/validate_cat_tavern.py \
  --api-key app-你的应用APIKey \
  --tavern-base http://127.0.0.1:8090 \
  --dify-base http://localhost:8080 \
  --out artifacts
```

脚本会清空两个测试玩家，跑三场对话并断言 9 项：

| # | 断言 |
| --- | --- |
| 1 | 第一场有符合人设的回答（不是空串，也不是报错） |
| 2 | 第一场开始时记忆为空（`旧事 0 条`） |
| 3 | 回答确实用了 seekdb 的传闻（`传闻 LORE-...`） |
| 4 | 这一轮行为写进了 PowerContext |
| 5 | **换一个新会话**后仍然读到这条旧事（`旧事 1 条`） |
| 6 | 好感度因这条旧事发生变化 |
| 7 | 换个 `player_id` 看不到别人的事（`旧事 0 条`） |
| 8 | PowerContext 里两个玩家的记忆确实互不相干 |
| 9 | seekdb 的 `lore_query_log` 有记录且命中非空 |

本次实测结果：**9/9 通过**，见 `artifacts/validation-20261027T110524Z.md`。
节点级执行轨迹（7 个节点全部 succeeded）见 `artifacts/dify-node-trace.json`。

## 说明与边界

* seekdb 这边用的是直白的词元匹配 + 权重排序（`seekdb_store.search_lore`），**没有**伪装成向量检索；
  16 张卡片的规模下这样最可解释，换成向量列也不影响 Dify 侧接线。
* 记忆是 append-only 的：`/debug/reset/{player_id}` 会写入一条「空记忆」工件并把指针指过去，
  而不是删旧工件——这样即使指针丢失，回退检索也不会把旧事翻出来。
* `.env`、`.state/`、`logs/` 已在 `.gitignore` 中；DSL 导出时使用 `include_secret=false`，不含任何密钥。
