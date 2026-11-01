export const EMBEDDING_DIMENSION = 384;
export const MODEL_ID = "Xenova/multilingual-e5-small";
export const MODEL_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78";

export interface KnowledgeBase {
  id: string;
  name: string;
  collectionName: string;
  modelId: string;
  modelRevision: string;
  dimension: number;
  chunkCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ChunkInput {
  id: string;
  document: string;
  embedding: number[];
  metadata: {
    documentId: string;
    sourceName: string;
    chunkIndex: number;
    charStart: number;
    charEnd: number;
    contentHash: string;
    importBatchId: string;
    modelId: string;
    modelRevision: string;
  };
}

export interface SearchResult {
  id: string;
  document: string;
  metadata: ChunkInput["metadata"];
  distance: number | null;
  rank: number;
}

export interface SearchResponse {
  results: SearchResult[];
  timings: {
    databaseMs: number;
  };
}

export type InferenceBackend = "webgpu" | "wasm";

export interface InferenceInfo {
  state: "idle" | "loading" | "ready" | "error";
  backend?: InferenceBackend;
  dtype?: "int8";
  modelId: string;
  loadMs?: number;
  fallbackReason?: string;
  progress?: number;
  progressFile?: string;
  error?: string;
}

export interface EmbeddingResult {
  embeddings: number[][];
  durationMs: number;
}
