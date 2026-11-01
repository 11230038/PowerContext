export interface TextChunk {
  text: string;
  charStart: number;
  charEnd: number;
  chunkIndex: number;
}

const TARGET_CHARS = 420;
const OVERLAP_CHARS = 60;

function preferredBreak(text: string, start: number, tentativeEnd: number): number {
  if (tentativeEnd >= text.length) return text.length;
  const floor = Math.min(tentativeEnd, start + Math.floor(TARGET_CHARS * 0.65));
  const segment = text.slice(floor, tentativeEnd);
  const separators = ["\n\n", "。", "！", "？", ". ", "\n", "；", "; "];
  let best = -1;
  let width = 0;
  for (const separator of separators) {
    const index = segment.lastIndexOf(separator);
    if (index > best) {
      best = index;
      width = separator.length;
    }
  }
  return best >= 0 ? floor + best + width : tentativeEnd;
}

export function chunkDocument(rawText: string): TextChunk[] {
  const text = rawText.replaceAll("\r\n", "\n").trim();
  if (!text) return [];

  const chunks: TextChunk[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    const tentativeEnd = Math.min(text.length, cursor + TARGET_CHARS);
    const end = preferredBreak(text, cursor, tentativeEnd);
    const value = text.slice(cursor, end).trim();
    if (value) {
      const leadingWhitespace = text.slice(cursor, end).search(/\S/);
      const actualStart = leadingWhitespace >= 0 ? cursor + leadingWhitespace : cursor;
      chunks.push({
        text: value,
        charStart: actualStart,
        charEnd: actualStart + value.length,
        chunkIndex: chunks.length,
      });
    }
    if (end >= text.length) break;
    const next = Math.max(cursor + 1, end - OVERLAP_CHARS);
    cursor = next;
  }
  return chunks;
}

export async function hashText(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
