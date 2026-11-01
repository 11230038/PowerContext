# SeekLocal：端侧 AI × seekdb 混合检索

SeekLocal 是一个完全在浏览器中生成文档与查询向量、使用本机 seekdb 存储并完成全文/向量混合检索的迷你知识库。

## 已实现

- TXT / Markdown 多文件导入、保守切块、确定性 ID 与增量 upsert。
- Transformers.js Web Worker 本地推理，不调用云端推理 API。
- `Xenova/multilingual-e5-small` INT8，固定模型 revision。
- 显式优先 `WebGPU`，初始化或推理不可用时自动降级到 `WASM`。
- seekdb Embedded 保存原文、384 维向量和元数据。
- IK 全文索引、HNSW cosine 向量索引和 seekdb 内部 RRF 混合排序。
- 写入结束后的显式 `refresh_index()`，刷新完成后才将导入标记为完成。
- 多知识库隔离、切换、增量导入和删除。
- 模型加载、文档向量化、写入、索引刷新、查询向量化、数据库检索和端到端计时。

## 运行要求

- Node.js 22 或更高版本。
- 最新版 Chrome / Edge。
- Windows x64、Linux x64/ARM64 或 macOS ARM64。
- 首次运行需要访问 Hugging Face 下载约 140 MB 的 INT8 模型及 tokenizer；之后使用浏览器缓存。

## 启动

```bash
cd stepfun
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>。开发模式会同时启动：

- Web：`127.0.0.1:5173`
- API：`127.0.0.1:8787`
- 数据：`stepfun/.data/seekdb`

生产模式：

```bash
npm run build
npm start
```

打开 <http://127.0.0.1:8787>。

> npm 使用 `.npmrc` 的 `legacy-peer-deps=true`，因为 seekdb 1.4.0 的可选服务端 embedding peer 发布包中残留了 `workspace:*`。本项目不安装该 peer，并始终传入浏览器生成的向量。

## 验收演示

1. 新建一个知识库。
2. 等待右上角显示 `WebGPU · INT8` 或 `WASM · INT8`。
3. 选择 `benchmark/corpus` 下的 Markdown 文件，观察向量化、写入和刷新阶段。
4. 搜索“浏览器不支持 WebGPU 时怎么办”。
5. 查看结果、来源、数据库耗时和端到端耗时。
6. 再导入一批文件，验证新增内容在刷新后可以检索。
7. 新建并切换知识库，验证结果互相隔离。

浏览器网络面板中只应出现模型静态文件下载和本机 `/api` 请求，不存在云端 inference 请求。服务端源码不调用 Transformers.js。

## 架构

```text
文件 → 浏览器切块 → Web Worker / Transformers.js → 原文 + embedding
                                                    ↓
                                             本机 Express API
                                                    ↓
                          seekdb collection: IK + HNSW + RRF hybridSearch
                                                    ↓
                                               已融合结果
```

关键约束：

- 写入调用 `collection.upsert({ embeddings })`。
- 查询调用 `hybridSearch({ knn: { queryEmbeddings } })`。
- 不调用 seekdb `queryTexts`，避免服务端自动 embedding。
- 不在客户端分别请求两路结果，也不在客户端融合排序。

## 验证命令

```bash
npm run check
npm run build
```

详细设计和当前实测见 [docs/TECHNICAL.md](docs/TECHNICAL.md)，测试集说明见 [benchmark/README.md](benchmark/README.md)。

## 常见问题

### 模型一直加载

确认可以访问 `huggingface.co`。模型 revision 已锁定为 `761b726dd34fb83930e26aab4e9ac3899aa1fa78`。

### WebGPU 自动降级

降级是预期行为。界面会显示原因，WASM 下的导入和检索仍然完整可用。可在 `edge://gpu` 或 `chrome://gpu` 检查浏览器支持。

### seekdb 原生绑定下载失败

首次启动 seekdb Embedded 可能下载平台对应的原生包。检查网络、Node 架构和系统是否在支持列表中。

### 清空本地演示数据

先停止服务，再移走 `stepfun/.data/seekdb`。不要在服务运行时直接删除数据库目录。
