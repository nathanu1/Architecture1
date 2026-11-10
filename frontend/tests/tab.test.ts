import { describe, expect, it } from "vitest";
import { mindById, MINDS, modelFor } from "../src/tab/mind";

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
