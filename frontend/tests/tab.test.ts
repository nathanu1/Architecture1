import { describe, expect, it } from "vitest";
import { thought } from "../src/lib/thought";
import { MEMORY_MODEL, mindById, MINDS, modelFor, packVectors } from "../src/tab/mind";
import titleFont from "../src/tab/title-font.json";

describe("minds for the town in a tab", () => {
  it("offers a no-download look and models from small to large, each with a full-precision twin", () => {
    expect(MINDS[0]).toMatchObject({ id: "scripted", model: null, downloadGB: 0 });
    const models = MINDS.filter((m) => m.model);
    expect(models.map((m) => m.id)).toEqual(["small", "standard", "bright", "large"]);
    for (const m of models) {
      expect(m.model).toMatch(/-q4f16_1-MLC$/);
      expect(m.modelF32).toBe(m.model!.replace("q4f16_1", "q4f32_1"));
    }
    expect([...models].sort((a, b) => a.downloadGB - b.downloadGB)).toEqual(models); // listed smallest first
  });

  it("picks the model file the graphics chip can run", () => {
    const bright = mindById("bright");
    expect(modelFor(bright, { f16: true })).toBe("Qwen3-4B-q4f16_1-MLC");
    expect(modelFor(bright, { f16: false })).toBe("Qwen3-4B-q4f32_1-MLC");
    expect(modelFor(mindById("scripted"), { f16: false })).toBeNull();
  });

  it("falls back to the scripted residents for an unknown mind and accepts a raw model id", () => {
    expect(mindById("nonsense").id).toBe("scripted");
    expect(mindById(null).id).toBe("scripted");
    const raw = mindById("SmolLM2-360M-Instruct-q4f32_1-MLC");
    expect(raw.model).toBe("SmolLM2-360M-Instruct-q4f32_1-MLC");
    expect(modelFor(raw, { f16: false })).toBe(raw.model);
  });
});

describe("memory by meaning", () => {
  it("packs vectors as the engine reads them: float32, little-endian, base64, in order", () => {
    const packed = packVectors([
      [1, 0.5, -2],
      [0, 0.25, 3],
    ]);
    expect(packed.count).toBe(2);
    const bytes = Uint8Array.from(atob(packed.data), (c) => c.charCodeAt(0));
    expect([...new Float32Array(bytes.buffer)]).toEqual([1, 0.5, -2, 0, 0.25, 3]);
    expect(packVectors([])).toEqual({ data: "", count: 0 });
    expect(MEMORY_MODEL).toMatch(/^snowflake-arctic-embed-s-.*-MLC/);
  });
});

describe("what a resident is thinking", () => {
  it("is said in plain words, per kind of thought", () => {
    expect(thought("day_plan")).toBe("is planning the day");
    expect(thought("dialogue_turn")).toBe("is finding the words");
    expect(thought("player_chat")).toBe("is thinking of a reply");
    expect(thought("something_new")).toBe("is thinking");
    expect(thought(undefined)).toBe("is thinking");
  });
});

describe("the 3D title", () => {
  it("has an outline for every letter of the town's name", () => {
    const glyphs = titleFont.glyphs as Record<string, { ha: number; o: string }>;
    for (const ch of "HEARTHSIDE") {
      expect(glyphs[ch].o.length).toBeGreaterThan(20);
      expect(glyphs[ch].ha).toBeGreaterThan(0);
    }
  });
});
