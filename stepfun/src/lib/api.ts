import type { ChunkInput, KnowledgeBase, SearchResponse } from "../types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(payload.error ?? `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  async listKnowledgeBases(): Promise<KnowledgeBase[]> {
    const payload = await request<{ knowledgeBases: KnowledgeBase[] }>("/api/knowledge-bases");
    return payload.knowledgeBases;
  },

  async createKnowledgeBase(name: string): Promise<KnowledgeBase> {
    const payload = await request<{ knowledgeBase: KnowledgeBase }>("/api/knowledge-bases", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    return payload.knowledgeBase;
  },

  deleteKnowledgeBase(id: string): Promise<void> {
    return request(`/api/knowledge-bases/${id}`, { method: "DELETE" });
  },

  async upsertChunks(id: string, chunks: ChunkInput[]): Promise<number> {
    const payload = await request<{ chunkCount: number }>(
      `/api/knowledge-bases/${id}/chunks`,
      { method: "POST", body: JSON.stringify({ chunks }) },
    );
    return payload.chunkCount;
  },

  refresh(id: string): Promise<{ chunkCount: number; refreshMs: number }> {
    return request(`/api/knowledge-bases/${id}/refresh`, {
      method: "POST",
      body: "{}",
    });
  },

  search(
    id: string,
    queryText: string,
    queryEmbedding: number[],
    topK = 10,
  ): Promise<SearchResponse> {
    return request(`/api/knowledge-bases/${id}/search`, {
      method: "POST",
      body: JSON.stringify({ queryText, queryEmbedding, topK, candidateK: 50 }),
    });
  },
};
