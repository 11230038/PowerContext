import { z } from "zod";
import { EMBEDDING_DIMENSION } from "../src/types";

export const createKnowledgeBaseSchema = z.object({
  name: z.string().trim().min(1).max(80),
});

const metadataSchema = z.object({
  documentId: z.string().min(1).max(128),
  sourceName: z.string().min(1).max(255),
  chunkIndex: z.number().int().nonnegative(),
  charStart: z.number().int().nonnegative(),
  charEnd: z.number().int().positive(),
  contentHash: z.string().min(16).max(128),
  importBatchId: z.string().min(1).max(128),
  modelId: z.string().min(1).max(255),
  modelRevision: z.string().min(1).max(128),
});

export const upsertChunksSchema = z.object({
  chunks: z.array(
    z.object({
      id: z.string().min(1).max(128),
      document: z.string().trim().min(1).max(20_000),
      embedding: z.array(z.number().finite()).length(EMBEDDING_DIMENSION),
      metadata: metadataSchema,
    }),
  ).min(1).max(128),
});

export const searchSchema = z.object({
  queryText: z.string().trim().min(1).max(1_000),
  queryEmbedding: z.array(z.number().finite()).length(EMBEDDING_DIMENSION),
  topK: z.number().int().min(1).max(50).default(10),
  candidateK: z.number().int().min(1).max(200).default(50),
});

export const idParamSchema = z.object({
  id: z.string().uuid(),
});
