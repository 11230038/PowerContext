/// <reference lib="webworker" />
import { env, pipeline } from "@huggingface/transformers";
import { EMBEDDING_DIMENSION, MODEL_ID, MODEL_REVISION } from "../types";

type Extractor = ((
  texts: string | string[],
  options: { pooling: "mean"; normalize: true },
) => Promise<{ tolist(): unknown }>) & {
  dispose?: () => Promise<void>;
};

interface InitMessage {
  type: "init";
}

interface EmbedMessage {
  type: "embed";
  id: string;
  texts: string[];
}

type IncomingMessage = InitMessage | EmbedMessage;

let extractor: Extractor | null = null;
let initialization: Promise<void> | null = null;
let wasmFallback: Promise<void> | null = null;
let backend: "webgpu" | "wasm" = "wasm";
let fallbackReason: string | undefined;
let totalLoadMs = 0;

env.allowLocalModels = false;
env.allowRemoteModels = true;
env.useBrowserCache = true;

function send(payload: unknown) {
  self.postMessage(payload);
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function loadFor(device: "webgpu" | "wasm") {
  return pipeline("feature-extraction", MODEL_ID, {
    revision: MODEL_REVISION,
    device,
    dtype: "int8",
    progress_callback: (progress: Record<string, unknown>) => {
      if (progress.status === "progress") {
        const raw = Number(progress.progress ?? 0);
        send({
          type: "progress",
          progress: raw > 1 ? raw / 100 : raw,
          file: String(progress.file ?? "模型文件"),
        });
      }
    },
  }) as Promise<unknown> as Promise<Extractor>;
}

async function loadAndWarmup(device: "webgpu" | "wasm"): Promise<Extractor> {
  const candidate = await loadFor(device);
  try {
    await candidate("query: warm up", { pooling: "mean", normalize: true });
    return candidate;
  } catch (error) {
    await candidate.dispose?.().catch(() => undefined);
    throw error;
  }
}

function sendReady() {
  send({
    type: "ready",
    backend,
    dtype: "int8",
    modelId: MODEL_ID,
    loadMs: totalLoadMs,
    fallbackReason,
  });
}

async function initialize() {
  if (extractor) return;
  const started = performance.now();
  send({ type: "state", state: "loading" });

  if ("gpu" in navigator) {
    try {
      extractor = await loadAndWarmup("webgpu");
      backend = "webgpu";
    } catch (error) {
      fallbackReason = `WebGPU 初始化或预热失败：${formatError(error)}`;
    }
  } else {
    fallbackReason = "当前浏览器未暴露 WebGPU";
  }

  if (!extractor) {
    extractor = await loadAndWarmup("wasm");
    backend = "wasm";
  }

  totalLoadMs += performance.now() - started;
  sendReady();
}

async function switchToWasm(error: unknown) {
  if (backend === "wasm" && extractor) return;
  if (!wasmFallback) {
    wasmFallback = (async () => {
      const started = performance.now();
      const previous = extractor;
      extractor = null;
      fallbackReason = `WebGPU 推理失败：${formatError(error)}`;
      send({ type: "state", state: "loading", fallbackReason });
      await previous?.dispose?.().catch(() => undefined);
      extractor = await loadAndWarmup("wasm");
      backend = "wasm";
      totalLoadMs += performance.now() - started;
      sendReady();
    })();
  }
  await wasmFallback;
}

async function runExtractor(texts: string[]): Promise<number[][]> {
  if (!extractor && wasmFallback) await wasmFallback;
  if (!extractor) throw new Error("模型未加载");
  const activeExtractor = extractor;
  const activeBackend = backend;
  try {
    const tensor = await activeExtractor(texts, { pooling: "mean", normalize: true });
    return tensor.tolist() as number[][];
  } catch (error) {
    if (activeBackend !== "webgpu") throw error;
    await switchToWasm(error);
    if (!extractor) throw new Error("WASM 模型未加载", { cause: error });
    const tensor = await extractor(texts, { pooling: "mean", normalize: true });
    return tensor.tolist() as number[][];
  }
}

async function embed(id: string, texts: string[]) {
  if (!initialization) initialization = initialize();
  await initialization;
  const started = performance.now();
  const embeddings = await runExtractor(texts);
  if (embeddings.some((value) => value.length !== EMBEDDING_DIMENSION)) {
    throw new Error(`模型输出维度异常，期望 ${EMBEDDING_DIMENSION}`);
  }
  send({
    type: "result",
    id,
    embeddings,
    durationMs: performance.now() - started,
  });
}

self.onmessage = async (event: MessageEvent<IncomingMessage>) => {
  try {
    if (event.data.type === "init") {
      if (!initialization) initialization = initialize();
      await initialization;
      return;
    }
    await embed(event.data.id, event.data.texts);
  } catch (error) {
    const message = formatError(error);
    send({ type: "error", id: event.data.type === "embed" ? event.data.id : undefined, error: message });
  }
};
