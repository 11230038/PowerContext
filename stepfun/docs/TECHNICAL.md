# SeekLocal 一页技术说明

## 模型与量化

模型为 `Xenova/multilingual-e5-small`，基础模型 `intfloat/multilingual-e5-small`，revision 固定为 `761b726dd34fb83930e26aab4e9ac3899aa1fa78`，输出 384 维向量。文档使用 `passage: `、查询使用 `query: ` 前缀，mean pooling 后 L2 normalize。默认采用 INT8 ONNX：官方仓库同一 revision 的 FP32 权重为 470,268,533 B，INT8 权重为 118,054,593 B，压缩比 3.984×；FP16 权重为 235,336,732 B，压缩比 1.998×。这些数字按单一 ONNX 权重口径统计，浏览器实际下载还包含约 22 MB tokenizer 和配置文件。质量使用 `benchmark/queries.json` 的 qrels 计算 Recall@5 与 nDCG@10，提交前需在目标设备分别导出 FP32/INT8 原始结果，不能用估算值代替。

## 端侧运行

推理运行在浏览器 Web Worker 的 Transformers.js 4.3.2 中，文档和查询均由同一 Worker 生成 embedding。初始化显式尝试 `device: "webgpu", dtype: "int8"`；浏览器没有 WebGPU、session 创建失败或推理失败时捕获异常并以 `device: "wasm", dtype: "int8"` 重建 pipeline。界面展示真实后端、精度、加载耗时和降级原因。模型只在 Worker 中创建一次，并执行一次 warm-up。WebGPU 批大小 16，WASM 批大小 4；下一批推理前完成上一批写入，以控制内存峰值。

## seekdb 使用

服务端使用 seekdb-js 1.4.0 Embedded，本机目录为 `.data/seekdb`。每个知识库对应独立 collection，另以 seekdb SQL 表 `knowledge_bases` 保存权威状态。collection 配置 IK `smart` 全文索引和 384 维 cosine HNSW（M=16、efConstruction=200、efSearch=100）。客户端提交原文、元数据和浏览器生成的向量，服务端调用 `upsert({ embeddings })`；服务端没有 embedding provider。查询提交原始查询词及浏览器生成的查询向量，单次 `hybridSearch()` 同时执行全文与 KNN 候选检索，并由 seekdb 用 RRF（window=50、k=60）融合，客户端不拼榜。所有批次写完后只调用一次 `refresh_index()`，成功后导入状态才变为完成。

## 状态、优化与实测

chunk ID 为知识库、文档、块序号和内容哈希的 SHA-256，可重复导入并 upsert。元数据记录源文件、字符范围、批次、模型及 revision；切换知识库实际切换 collection。文本以约 420 字符、60 字符 overlap 保守切块，避免中文超过 512 token。模型和数据库连接均复用，浏览器 UI 分阶段使用 `performance.now()` 计时。2026-10-31 在当前 Windows x64 开发环境完成数据库冒烟测试：写入 1 个 384 维 chunk，显式刷新 323.14 ms，数据库内混合检索 11.82 ms，Top-1 返回预期文档；该数据仅证明链路，不作为正式性能结论。正式结果必须固定设备、Chrome/Edge 版本、语料与查询集，分别记录冷/热加载，每项重复至少 10 次并报告中位数与 P95。
