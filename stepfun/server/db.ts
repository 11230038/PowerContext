import path from "node:path";
import {
  FulltextIndexConfig,
  Schema,
  SeekdbAdminClient,
  SeekdbClient,
  VectorIndexConfig,
  type Collection,
  type Metadata,
} from "seekdb";
import {
  EMBEDDING_DIMENSION,
  MODEL_ID,
  MODEL_REVISION,
  type ChunkInput,
  type KnowledgeBase,
  type SearchResponse,
} from "../src/types";

interface KnowledgeBaseRow {
  id: string;
  name: string;
  collection_name: string;
  model_id: string;
  model_revision: string;
  dimension: number;
  created_at: Date | string;
  updated_at: Date | string;
}

const DATA_PATH = process.env.SEEKDB_PATH
  ? path.resolve(process.env.SEEKDB_PATH)
  : path.resolve(process.cwd(), ".data", "seekdb");

function toIso(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : date.toISOString();
}

function collectionName(id: string): string {
  return `kb_${id.replaceAll("-", "")}`;
}

function fromRow(row: KnowledgeBaseRow, chunkCount = 0): KnowledgeBase {
  return {
    id: row.id,
    name: row.name,
    collectionName: row.collection_name,
    modelId: row.model_id,
    modelRevision: row.model_revision,
    dimension: Number(row.dimension),
    chunkCount,
    createdAt: toIso(row.created_at),
    updatedAt: toIso(row.updated_at),
  };
}

export class KnowledgeStore {
  private client: SeekdbClient | null = null;
  private initialization: Promise<void> | null = null;

  async initialize(): Promise<void> {
    if (this.initialization) return this.initialization;
    this.initialization = this.initializeOnce();
    return this.initialization;
  }

  private async initializeOnce(): Promise<void> {
    const admin = new SeekdbAdminClient({ path: DATA_PATH });
    try {
      const databases = await admin.listDatabases();
      if (!databases.some((database) => database.name === "seeklocal")) {
        await admin.createDatabase("seeklocal");
      }
    } finally {
      await admin.close();
    }
    this.client = new SeekdbClient({
      path: DATA_PATH,
      database: "seeklocal",
    });
    await this.client.execute(`
      CREATE TABLE IF NOT EXISTS knowledge_bases (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        name VARCHAR(80) NOT NULL,
        collection_name VARCHAR(64) NOT NULL UNIQUE,
        model_id VARCHAR(255) NOT NULL,
        model_revision VARCHAR(128) NOT NULL,
        dimension INT NOT NULL,
        created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
      )
    `);
  }

  private async db(): Promise<SeekdbClient> {
    await this.initialize();
    if (!this.client) throw new Error("seekdb 尚未初始化");
    return this.client;
  }

  async health(): Promise<{ connected: boolean; path: string }> {
    const client = await this.db();
    await client.execute("SELECT 1 AS ok");
    return { connected: client.isConnected(), path: DATA_PATH };
  }

  async listKnowledgeBases(): Promise<KnowledgeBase[]> {
    const client = await this.db();
    const rows = await client.execute(
      "SELECT * FROM knowledge_bases ORDER BY updated_at DESC",
    ) as unknown as KnowledgeBaseRow[] | null;
    if (!rows) return [];

    return Promise.all(rows.map(async (row) => {
      let count = 0;
      try {
        count = await (await client.getCollection({
          name: row.collection_name,
          embeddingFunction: null,
        })).count();
      } catch {
        // A partially-created knowledge base is still listed and can be diagnosed.
      }
      return fromRow(row, count);
    }));
  }

  async createKnowledgeBase(name: string): Promise<KnowledgeBase> {
    const client = await this.db();
    const id = crypto.randomUUID();
    const nameForCollection = collectionName(id);
    const schema = new Schema()
      .createIndex(new FulltextIndexConfig("ik", { ik_mode: "smart" }))
      .createIndex(new VectorIndexConfig({
        hnsw: {
          dimension: EMBEDDING_DIMENSION,
          distance: "cosine",
          type: "hnsw",
          lib: "vsag",
          m: 16,
          ef_construction: 200,
          ef_search: 100,
        },
        embeddingFunction: null,
      }));

    await client.createCollection({
      name: nameForCollection,
      schema,
      embeddingFunction: null,
    });

    try {
      await client.execute(
        `INSERT INTO knowledge_bases
          (id, name, collection_name, model_id, model_revision, dimension)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [id, name, nameForCollection, MODEL_ID, MODEL_REVISION, EMBEDDING_DIMENSION],
      );
    } catch (error) {
      await client.deleteCollection(nameForCollection).catch(() => undefined);
      throw error;
    }

    return this.getKnowledgeBase(id);
  }

  async getKnowledgeBase(id: string): Promise<KnowledgeBase> {
    const client = await this.db();
    const rows = await client.execute(
      "SELECT * FROM knowledge_bases WHERE id = ? LIMIT 1",
      [id],
    ) as unknown as KnowledgeBaseRow[] | null;
    if (!rows?.length) throw new Error("知识库不存在");
    const collection = await client.getCollection({
      name: rows[0].collection_name,
      embeddingFunction: null,
    });
    return fromRow(rows[0], await collection.count());
  }

  private async collectionFor(id: string): Promise<{ kb: KnowledgeBase; collection: Collection }> {
    const client = await this.db();
    const kb = await this.getKnowledgeBase(id);
    const collection = await client.getCollection({
      name: kb.collectionName,
      embeddingFunction: null,
    });
    return { kb, collection };
  }

  async upsertChunks(id: string, chunks: ChunkInput[]): Promise<number> {
    const client = await this.db();
    const { kb, collection } = await this.collectionFor(id);
    for (const chunk of chunks) {
      if (chunk.metadata.modelId !== kb.modelId) {
        throw new Error(`模型不匹配：知识库要求 ${kb.modelId}`);
      }
    }
    await collection.upsert({
      ids: chunks.map((chunk) => chunk.id),
      documents: chunks.map((chunk) => chunk.document),
      embeddings: chunks.map((chunk) => chunk.embedding),
      metadatas: chunks.map((chunk) => chunk.metadata as unknown as Metadata),
    });
    await client.execute(
      "UPDATE knowledge_bases SET updated_at = CURRENT_TIMESTAMP(6) WHERE id = ?",
      [id],
    );
    return collection.count();
  }

  async refresh(id: string): Promise<number> {
    const { collection } = await this.collectionFor(id);
    await collection.refresh_index();
    return collection.count();
  }

  async search(
    id: string,
    queryText: string,
    queryEmbedding: number[],
    topK: number,
    candidateK: number,
  ): Promise<SearchResponse> {
    const { collection } = await this.collectionFor(id);
    const start = performance.now();
    const result = await collection.hybridSearch<ChunkInput["metadata"]>({
      query: {
        whereDocument: { $contains: queryText },
        nResults: candidateK,
      },
      knn: {
        queryEmbeddings: [queryEmbedding],
        nResults: candidateK,
      },
      rank: {
        rrf: {
          rankWindowSize: candidateK,
          rankConstant: 60,
        },
      },
      nResults: topK,
      include: ["documents", "metadatas", "distances"],
    });
    const databaseMs = performance.now() - start;
    const ids = result.ids[0] ?? [];
    const documents = result.documents?.[0] ?? [];
    const metadatas = result.metadatas?.[0] ?? [];
    const distances = result.distances?.[0] ?? [];

    return {
      results: ids.map((resultId, index) => ({
        id: resultId,
        document: documents[index] ?? "",
        metadata: metadatas[index] as ChunkInput["metadata"],
        distance: distances[index] ?? null,
        rank: index + 1,
      })),
      timings: { databaseMs },
    };
  }

  async deleteKnowledgeBase(id: string): Promise<void> {
    const client = await this.db();
    const kb = await this.getKnowledgeBase(id);
    await client.deleteCollection(kb.collectionName);
    await client.execute("DELETE FROM knowledge_bases WHERE id = ?", [id]);
  }

  async close(): Promise<void> {
    if (this.client) await this.client.close();
    this.client = null;
    this.initialization = null;
  }
}

export const store = new KnowledgeStore();
