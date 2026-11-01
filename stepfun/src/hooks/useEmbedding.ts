import { useCallback, useEffect, useRef, useState } from "react";
import {
  MODEL_ID,
  type EmbeddingResult,
  type InferenceInfo,
} from "../types";

interface PendingRequest {
  resolve: (result: EmbeddingResult) => void;
  reject: (error: Error) => void;
}

export function useEmbedding() {
  const workerRef = useRef<Worker | null>(null);
  const pendingRef = useRef(new Map<string, PendingRequest>());
  const [info, setInfo] = useState<InferenceInfo>({
    state: "loading",
    modelId: MODEL_ID,
  });

  useEffect(() => {
    const worker = new Worker(
      new URL("../workers/embedding.worker.ts", import.meta.url),
      { type: "module" },
    );
    workerRef.current = worker;
    const pendingRequests = pendingRef.current;

    worker.onmessage = (event) => {
      const message = event.data;
      if (message.type === "state") {
        setInfo((current) => ({
          ...current,
          state: message.state,
          fallbackReason: message.fallbackReason ?? current.fallbackReason,
        }));
      } else if (message.type === "progress") {
        setInfo((current) => ({
          ...current,
          state: "loading",
          progress: message.progress,
          progressFile: message.file,
        }));
      } else if (message.type === "ready") {
        setInfo({
          state: "ready",
          backend: message.backend,
          dtype: message.dtype,
          modelId: message.modelId,
          loadMs: message.loadMs,
          fallbackReason: message.fallbackReason,
          progress: 1,
        });
      } else if (message.type === "result") {
        const pending = pendingRequests.get(message.id);
        if (pending) {
          pending.resolve({ embeddings: message.embeddings, durationMs: message.durationMs });
          pendingRequests.delete(message.id);
        }
      } else if (message.type === "error") {
        const error = new Error(message.error);
        const pending = message.id ? pendingRequests.get(message.id) : undefined;
        if (pending) {
          pending.reject(error);
          pendingRequests.delete(message.id);
        } else {
          setInfo((current) => ({ ...current, state: "error", error: message.error }));
        }
      }
    };
    worker.postMessage({ type: "init" });

    return () => {
      worker.terminate();
      workerRef.current = null;
      for (const pending of pendingRequests.values()) {
        pending.reject(new Error("Embedding Worker 已关闭"));
      }
      pendingRequests.clear();
    };
  }, []);

  const embed = useCallback((texts: string[]): Promise<EmbeddingResult> => {
    if (!workerRef.current) return Promise.reject(new Error("Embedding Worker 尚未启动"));
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      pendingRef.current.set(id, { resolve, reject });
      workerRef.current!.postMessage({ type: "embed", id, texts });
    });
  }, []);

  return { info, embed };
}
