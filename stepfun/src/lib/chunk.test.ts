import { describe, expect, it } from "vitest";
import { chunkDocument } from "./chunk";

describe("chunkDocument", () => {
  it("returns no chunks for blank input", () => {
    expect(chunkDocument("  \n ")).toEqual([]);
  });

  it("preserves short content", () => {
    expect(chunkDocument("seekdb 混合检索")).toEqual([{
      text: "seekdb 混合检索",
      charStart: 0,
      charEnd: 11,
      chunkIndex: 0,
    }]);
  });

  it("splits long content with overlap", () => {
    const chunks = chunkDocument("端侧推理。".repeat(120));
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((chunk) => chunk.text.length <= 420)).toBe(true);
    expect(chunks[1].charStart).toBeLessThan(chunks[0].charEnd);
  });
});
