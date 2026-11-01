import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useEmbedding } from "./hooks/useEmbedding";
import { api } from "./lib/api";
import { chunkDocument, hashText } from "./lib/chunk";
import {
  MODEL_ID,
  MODEL_REVISION,
  type ChunkInput,
  type KnowledgeBase,
  type SearchResult,
} from "./types";

interface ImportState {
  stage: "idle" | "reading" | "embedding" | "writing" | "refreshing" | "done" | "error";
  progress: number;
  message: string;
  embeddingMs?: number;
  writeMs?: number;
  refreshMs?: number;
}

interface QueryTimings {
  embeddingMs: number;
  databaseMs: number;
  endToEndMs: number;
}

const initialImportState: ImportState = {
  stage: "idle",
  progress: 0,
  message: "等待导入",
};

function formatMs(value?: number) {
  if (value === undefined) return "—";
  return value < 1 ? `${value.toFixed(2)} ms` : `${Math.round(value)} ms`;
}

function formatCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function basename(fileName: string) {
  return fileName.replace(/\.(txt|md|markdown)$/i, "");
}

export default function App() {
  const { info, embed } = useEmbedding();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [activeId, setActiveId] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [loadingBases, setLoadingBases] = useState(true);
  const [importState, setImportState] = useState<ImportState>(initialImportState);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [queryTimings, setQueryTimings] = useState<QueryTimings | null>(null);
  const [error, setError] = useState("");

  const activeBase = useMemo(
    () => knowledgeBases.find((item) => item.id === activeId),
    [knowledgeBases, activeId],
  );

  async function reloadBases(preferredId?: string) {
    const items = await api.listKnowledgeBases();
    setKnowledgeBases(items);
    setActiveId((current) => {
      const target = preferredId ?? current;
      return items.some((item) => item.id === target) ? target : (items[0]?.id ?? "");
    });
  }

  useEffect(() => {
    let active = true;
    void Promise.resolve()
      .then(() => reloadBases())
      .catch((cause) => {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (active) setLoadingBases(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function createKnowledgeBase(event: FormEvent) {
    event.preventDefault();
    if (!newName.trim() || creating) return;
    setCreating(true);
    setError("");
    try {
      const created = await api.createKnowledgeBase(newName.trim());
      setNewName("");
      await reloadBases(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setCreating(false);
    }
  }

  async function deleteActiveBase() {
    if (!activeBase) return;
    if (!window.confirm(`确定删除知识库“${activeBase.name}”及其全部向量吗？此操作不可撤销。`)) return;
    setError("");
    try {
      await api.deleteKnowledgeBase(activeBase.id);
      setResults([]);
      await reloadBases();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function importFiles(files: FileList | null) {
    if (!files?.length || !activeBase || info.state !== "ready") return;
    const selected = Array.from(files).filter((file) => /\.(txt|md|markdown)$/i.test(file.name));
    if (!selected.length) {
      setError("请选择 TXT 或 Markdown 文件");
      return;
    }

    setError("");
    setResults([]);
    setImportState({ stage: "reading", progress: 0.03, message: "读取并切分文档…" });
    const importBatchId = crypto.randomUUID();
    let totalEmbeddingMs = 0;
    let totalWriteMs = 0;

    try {
      const prepared: Array<Omit<ChunkInput, "embedding">> = [];
      for (const file of selected) {
        const content = await file.text();
        const documentId = await hashText(`${file.name}:${file.size}:${file.lastModified}`);
        const chunks = chunkDocument(content);
        for (const chunk of chunks) {
          const contentHash = await hashText(chunk.text);
          prepared.push({
            id: await hashText(`${activeBase.id}:${documentId}:${chunk.chunkIndex}:${contentHash}`),
            document: chunk.text,
            metadata: {
              documentId,
              sourceName: file.name,
              chunkIndex: chunk.chunkIndex,
              charStart: chunk.charStart,
              charEnd: chunk.charEnd,
              contentHash,
              importBatchId,
              modelId: MODEL_ID,
              modelRevision: MODEL_REVISION,
            },
          });
        }
      }
      if (!prepared.length) throw new Error("所选文件没有可导入的文本内容");

      const batchSize = info.backend === "webgpu" ? 16 : 4;
      for (let offset = 0; offset < prepared.length; offset += batchSize) {
        const batch = prepared.slice(offset, offset + batchSize);
        const completedRatio = offset / prepared.length;
        setImportState({
          stage: "embedding",
          progress: 0.08 + completedRatio * 0.72,
          message: `本地向量化 ${Math.min(offset + batch.length, prepared.length)} / ${prepared.length}`,
          embeddingMs: totalEmbeddingMs,
          writeMs: totalWriteMs,
        });
        const embeddingResult = await embed(batch.map((chunk) => `passage: ${chunk.document}`));
        totalEmbeddingMs += embeddingResult.durationMs;

        setImportState({
          stage: "writing",
          progress: 0.12 + completedRatio * 0.72,
          message: `写入 seekdb ${Math.min(offset + batch.length, prepared.length)} / ${prepared.length}`,
          embeddingMs: totalEmbeddingMs,
          writeMs: totalWriteMs,
        });
        const writeStarted = performance.now();
        await api.upsertChunks(activeBase.id, batch.map((chunk, index) => ({
          ...chunk,
          embedding: embeddingResult.embeddings[index],
        })));
        totalWriteMs += performance.now() - writeStarted;
      }

      setImportState({
        stage: "refreshing",
        progress: 0.9,
        message: "刷新全文与向量索引…",
        embeddingMs: totalEmbeddingMs,
        writeMs: totalWriteMs,
      });
      const refreshed = await api.refresh(activeBase.id);
      setImportState({
        stage: "done",
        progress: 1,
        message: `已导入 ${selected.length} 个文件，共 ${prepared.length} 个文本块`,
        embeddingMs: totalEmbeddingMs,
        writeMs: totalWriteMs,
        refreshMs: refreshed.refreshMs,
      });
      await reloadBases(activeBase.id);
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause);
      setImportState({ stage: "error", progress: 0, message });
      setError(message);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim() || !activeBase || info.state !== "ready" || searching) return;
    setSearching(true);
    setError("");
    const started = performance.now();
    try {
      const embeddingResult = await embed([`query: ${query.trim()}`]);
      const response = await api.search(
        activeBase.id,
        query.trim(),
        embeddingResult.embeddings[0],
      );
      setResults(response.results);
      setQueryTimings({
        embeddingMs: embeddingResult.durationMs,
        databaseMs: response.timings.databaseMs,
        endToEndMs: performance.now() - started,
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSearching(false);
    }
  }

  const inferenceLabel = info.state === "ready"
    ? `${info.backend === "webgpu" ? "WebGPU" : "WASM"} · ${info.dtype?.toUpperCase()}`
    : info.state === "error" ? "模型加载失败" : "模型加载中";

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">S</span>
          <div>
            <strong>SeekLocal</strong>
            <span>端侧智能知识库</span>
          </div>
        </div>
        <div className="runtime-status" title={info.fallbackReason}>
          <span className={`status-dot ${info.state}`} />
          <div>
            <small>浏览器本地推理</small>
            <strong>{inferenceLabel}</strong>
          </div>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="sidebar-heading">
            <span>知识库</span>
            <span className="count-pill">{knowledgeBases.length}</span>
          </div>

          <div className="kb-list" aria-label="知识库列表">
            {loadingBases && <p className="muted">连接 seekdb…</p>}
            {!loadingBases && !knowledgeBases.length && (
              <div className="empty-mini">创建第一个知识库以开始</div>
            )}
            {knowledgeBases.map((kb) => (
              <button
                className={`kb-item ${kb.id === activeId ? "active" : ""}`}
                key={kb.id}
                onClick={() => {
                  setActiveId(kb.id);
                  setResults([]);
                  setImportState(initialImportState);
                }}
              >
                <span className="kb-icon">⌁</span>
                <span className="kb-copy">
                  <strong>{kb.name}</strong>
                  <small>{formatCount(kb.chunkCount)} 个文本块</small>
                </span>
              </button>
            ))}
          </div>

          <form className="new-kb" onSubmit={createKnowledgeBase}>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="新知识库名称"
              maxLength={80}
              aria-label="新知识库名称"
            />
            <button type="submit" disabled={!newName.trim() || creating}>
              {creating ? "…" : "+"}
            </button>
          </form>
        </aside>

        <main className="main-content">
          {!activeBase ? (
            <section className="welcome-card">
              <span className="eyebrow">LOCAL-FIRST RAG</span>
              <h1>把文档留在自己的设备上</h1>
              <p>创建知识库后，浏览器会在本地生成向量，再交给 seekdb 完成全文与语义混合检索。</p>
            </section>
          ) : (
            <>
              <section className="page-heading">
                <div>
                  <span className="eyebrow">CURRENT KNOWLEDGE BASE</span>
                  <h1>{activeBase.name}</h1>
                  <p>{formatCount(activeBase.chunkCount)} 个文本块 · 384 维 cosine 向量</p>
                </div>
                <button className="ghost danger" onClick={deleteActiveBase}>删除知识库</button>
              </section>

              {error && (
                <div className="error-banner" role="alert">
                  <span>!</span>
                  <p>{error}</p>
                  <button onClick={() => setError("")} aria-label="关闭错误提示">×</button>
                </div>
              )}

              <section className="search-panel">
                <form className="search-box" onSubmit={search}>
                  <span className="search-glyph">⌕</span>
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="输入问题，同时检索语义与关键词…"
                    disabled={!activeBase.chunkCount}
                  />
                  <button
                    type="submit"
                    disabled={!query.trim() || searching || info.state !== "ready" || !activeBase.chunkCount}
                  >
                    {searching ? "检索中" : "混合检索"}
                  </button>
                </form>
                {queryTimings && (
                  <div className="timing-strip">
                    <span>查询向量 <strong>{formatMs(queryTimings.embeddingMs)}</strong></span>
                    <span>seekdb <strong>{formatMs(queryTimings.databaseMs)}</strong></span>
                    <span>端到端 <strong>{formatMs(queryTimings.endToEndMs)}</strong></span>
                  </div>
                )}
              </section>

              <div className="content-grid">
                <section className="card import-card">
                  <div className="card-title">
                    <div>
                      <span className="step-number">01</span>
                      <h2>导入语料</h2>
                    </div>
                    <span className="format-badge">TXT · MD</span>
                  </div>
                  <button
                    className="drop-zone"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={info.state !== "ready" || ["reading", "embedding", "writing", "refreshing"].includes(importState.stage)}
                  >
                    <span className="upload-symbol">↥</span>
                    <strong>选择本地文档</strong>
                    <small>文本在浏览器内切块和向量化</small>
                  </button>
                  <input
                    ref={fileInputRef}
                    className="sr-only"
                    type="file"
                    accept=".txt,.md,.markdown,text/plain,text/markdown"
                    multiple
                    onChange={(event) => importFiles(event.target.files)}
                  />
                  <div className="progress-block">
                    <div className="progress-copy">
                      <span>{importState.message}</span>
                      <strong>{Math.round(importState.progress * 100)}%</strong>
                    </div>
                    <div className="progress-track">
                      <span style={{ width: `${importState.progress * 100}%` }} />
                    </div>
                  </div>
                  <div className="mini-metrics">
                    <div><small>本地向量化</small><strong>{formatMs(importState.embeddingMs)}</strong></div>
                    <div><small>写入</small><strong>{formatMs(importState.writeMs)}</strong></div>
                    <div><small>索引刷新</small><strong>{formatMs(importState.refreshMs)}</strong></div>
                  </div>
                </section>

                <section className="card runtime-card">
                  <div className="card-title">
                    <div>
                      <span className="step-number">02</span>
                      <h2>推理诊断</h2>
                    </div>
                    <span className={`live-badge ${info.state}`}>{info.state === "ready" ? "READY" : info.state.toUpperCase()}</span>
                  </div>
                  <dl className="diagnostics">
                    <div><dt>模型</dt><dd>{basename(info.modelId.split("/").at(-1) ?? info.modelId)}</dd></div>
                    <div><dt>执行位置</dt><dd>当前浏览器</dd></div>
                    <div><dt>推理后端</dt><dd>{info.backend?.toUpperCase() ?? "检测中"}</dd></div>
                    <div><dt>模型精度</dt><dd>{info.dtype?.toUpperCase() ?? "INT8"}</dd></div>
                    <div><dt>模型加载</dt><dd>{formatMs(info.loadMs)}</dd></div>
                  </dl>
                  {info.state === "loading" && (
                    <div className="model-progress">
                      <div><span>{info.progressFile ?? "初始化运行时"}</span><strong>{Math.round((info.progress ?? 0) * 100)}%</strong></div>
                      <div className="progress-track"><span style={{ width: `${(info.progress ?? 0) * 100}%` }} /></div>
                    </div>
                  )}
                  {info.fallbackReason && (
                    <p className="fallback-note">已自动降级至 WASM：{info.fallbackReason}</p>
                  )}
                  {info.error && (
                    <p className="model-error">模型加载失败：{info.error}</p>
                  )}
                </section>
              </div>

              <section className="results-section">
                <div className="results-heading">
                  <div>
                    <span className="eyebrow">DATABASE-FUSED RANKING</span>
                    <h2>检索结果</h2>
                  </div>
                  <span>{results.length ? `${results.length} 条结果` : "RRF 融合排序"}</span>
                </div>
                {!results.length ? (
                  <div className="empty-results">
                    <span>⌕</span>
                    <p>{activeBase.chunkCount ? "输入问题，查看 seekdb 混合检索结果" : "先导入文档，再开始检索"}</p>
                  </div>
                ) : (
                  <div className="result-list">
                    {results.map((result) => (
                      <article className="result-card" key={result.id}>
                        <div className="rank">{String(result.rank).padStart(2, "0")}</div>
                        <div className="result-body">
                          <div className="result-meta">
                            <strong>{result.metadata?.sourceName ?? "未知来源"}</strong>
                            <span>chunk {result.metadata?.chunkIndex ?? "—"}</span>
                            {result.distance !== null && <span>distance {result.distance.toFixed(4)}</span>}
                          </div>
                          <p>{result.document}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
