import path from "node:path";
import { fileURLToPath } from "node:url";
import express, { type ErrorRequestHandler } from "express";
import { ZodError } from "zod";
import { store } from "./db";
import {
  createKnowledgeBaseSchema,
  idParamSchema,
  searchSchema,
  upsertChunksSchema,
} from "./schemas";

const app = express();
const port = Number(process.env.PORT ?? 8787);
const host = process.env.HOST ?? "127.0.0.1";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// The current Windows embedded binding can invalidate the inherited stdout and
// stderr handles after startup. Ignore that specific stream error so a log
// statement cannot terminate an otherwise healthy API process.
function handleProcessStreamError(error: NodeJS.ErrnoException) {
  if (process.platform !== "win32" || error.code !== "EBADF") throw error;
}

process.stdout.on("error", handleProcessStreamError);
process.stderr.on("error", handleProcessStreamError);

app.disable("x-powered-by");
app.use((_request, response, next) => {
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  next();
});
app.use(express.json({ limit: "12mb" }));

app.get("/api/health", async (_request, response) => {
  response.json({ ok: true, database: await store.health() });
});

app.get("/api/knowledge-bases", async (_request, response) => {
  response.json({ knowledgeBases: await store.listKnowledgeBases() });
});

app.post("/api/knowledge-bases", async (request, response) => {
  const input = createKnowledgeBaseSchema.parse(request.body);
  response.status(201).json({ knowledgeBase: await store.createKnowledgeBase(input.name) });
});

app.delete("/api/knowledge-bases/:id", async (request, response) => {
  const { id } = idParamSchema.parse(request.params);
  await store.deleteKnowledgeBase(id);
  response.status(204).end();
});

app.post("/api/knowledge-bases/:id/chunks", async (request, response) => {
  const { id } = idParamSchema.parse(request.params);
  const { chunks } = upsertChunksSchema.parse(request.body);
  const chunkCount = await store.upsertChunks(id, chunks);
  response.json({ chunkCount });
});

app.post("/api/knowledge-bases/:id/refresh", async (request, response) => {
  const { id } = idParamSchema.parse(request.params);
  const started = performance.now();
  const chunkCount = await store.refresh(id);
  response.json({ chunkCount, refreshMs: performance.now() - started });
});

app.post("/api/knowledge-bases/:id/search", async (request, response) => {
  const { id } = idParamSchema.parse(request.params);
  const input = searchSchema.parse(request.body);
  response.json(await store.search(
    id,
    input.queryText,
    input.queryEmbedding,
    input.topK,
    input.candidateK,
  ));
});

if (process.env.NODE_ENV === "production" || process.env.npm_lifecycle_event === "start") {
  app.use(express.static(path.join(root, "dist")));
  app.get("/{*splat}", (_request, response) => {
    response.sendFile(path.join(root, "dist", "index.html"));
  });
}

const errorHandler: ErrorRequestHandler = (error, _request, response, _next) => {
  console.error(error);
  if (error instanceof ZodError) {
    response.status(400).json({
      error: "请求数据不合法",
      issues: error.issues,
    });
    return;
  }
  const message = error instanceof Error ? error.message : "服务器内部错误";
  const status = message.includes("不存在") ? 404 : 500;
  response.status(status).json({ error: message });
};
app.use(errorHandler);

const server = app.listen(port, host, async () => {
  try {
    await store.initialize();
    console.log(`SeekLocal API: http://${host}:${port}`);
  } catch (error) {
    console.error("seekdb 初始化失败", error);
  }
});

async function shutdown() {
  server.close();
  await store.close().catch(console.error);
  if (process.platform === "win32") {
    // The embedded binding currently blocks in its environment cleanup hook on
    // Windows. A forced self-signal releases the database files immediately.
    process.kill(process.pid, "SIGKILL");
    return;
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
