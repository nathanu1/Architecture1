import { tabTown } from "./client";
import type { Answer, Need, Vectors } from "./protocol";

/** How the residents think: scripted, or a language model that runs on this device's graphics chip. */
export interface Mind {
  id: string;
  /** The model's id in the in-browser runtime (WebLLM); null for the scripted residents. */
  model: string | null;
  /** The same model in full precision, for graphics chips without half-float support (needs about a third more memory). */
  modelF32?: string;
  name: string;
  blurb: string;
  downloadGB: number;
  /** Graphics memory the model needs, in GB (from the runtime's own model list). */
  memoryGB: number;
}

// Model ids, memory needs and download sizes are those of @mlc-ai/web-llm 0.2.87's prebuilt list.
// "Bright" is a 4B model that its authors report ahead of the 8B on standard benchmarks at half
// the download (Qwen3 technical report); the 8B stays available for machines that can hold it.
export const MINDS: Mind[] = [
  { id: "scripted", model: null, name: "Look Around", blurb: "No download", downloadGB: 0, memoryGB: 0 },
  { id: "small", model: "Llama-3.2-1B-Instruct-q4f16_1-MLC", modelF32: "Llama-3.2-1B-Instruct-q4f32_1-MLC", name: "Small", blurb: "0.7\u00a0GB, once", downloadGB: 0.7, memoryGB: 0.9 },
  { id: "standard", model: "Llama-3.2-3B-Instruct-q4f16_1-MLC", modelF32: "Llama-3.2-3B-Instruct-q4f32_1-MLC", name: "Standard", blurb: "1.8\u00a0GB, once", downloadGB: 1.8, memoryGB: 2.3 },
  { id: "bright", model: "Qwen3-4B-q4f16_1-MLC", modelF32: "Qwen3-4B-q4f32_1-MLC", name: "Bright", blurb: "2.3\u00a0GB, once", downloadGB: 2.3, memoryGB: 3.4 },
  { id: "large", model: "Llama-3.1-8B-Instruct-q4f16_1-MLC", modelF32: "Llama-3.1-8B-Instruct-q4f32_1-MLC", name: "Largest", blurb: "4.5\u00a0GB, once", downloadGB: 4.5, memoryGB: 5.0 },
];

export interface Device {
  /** Can this browser run a model on the graphics chip at all? */
  webgpu: boolean;
  /** Does the graphics chip support half-precision numbers (the smaller, faster model files)? */
  f16: boolean;
  phone: boolean;
  /** Reported memory in GB (Chrome only, capped at 8), or null. */
  memoryGB: number | null;
  /** The mind to preselect. */
  suggested: string;
  /** A few words when minds are unavailable here, else empty. */
  why: string;
}

interface GPUAdapterLike {
  features: { has(name: string): boolean };
}

export async function lookAtDevice(): Promise<Device> {
  const nav = navigator as Navigator & { gpu?: { requestAdapter(): Promise<GPUAdapterLike | null> }; deviceMemory?: number };
  const phone = /Android|iPhone|iPad|Mobile/i.test(nav.userAgent);
  const memoryGB = typeof nav.deviceMemory === "number" ? nav.deviceMemory : null;
  let webgpu = false;
  let f16 = false;
  try {
    const adapter = await nav.gpu?.requestAdapter();
    webgpu = !!adapter;
    f16 = !!adapter?.features.has("shader-f16");
  } catch {
    webgpu = false;
  }
  if (!webgpu) return { webgpu, f16, phone, memoryGB, suggested: "scripted", why: "Minds need Chrome or Edge on a computer. You can still look around." };
  if (phone || (memoryGB !== null && memoryGB <= 4)) return { webgpu, f16, phone, memoryGB, suggested: "small", why: "" };
  return { webgpu, f16, phone, memoryGB, suggested: "standard", why: "" };
}

/** A mind by its id; a raw runtime model id (it ends in "-MLC") is accepted too, for the curious. */
export function mindById(id: string | null | undefined): Mind {
  const known = MINDS.find((m) => m.id === id);
  if (known) return known;
  if (id && id.endsWith("-MLC")) return { id, model: id, name: id, blurb: "", downloadGB: 0, memoryGB: 0 };
  return MINDS[0];
}

/** The model file that fits this graphics chip. */
export const modelFor = (mind: Mind, device: Pick<Device, "f16"> | null): string | null => (mind.model && mind.modelF32 && device && !device.f16 ? mind.modelF32 : mind.model);

interface Engine {
  chat: { completions: { create(body: Record<string, unknown>): Promise<Completion> } };
  interruptGenerate(): void | Promise<void>;
}
interface Completion {
  choices: { message: { content: string | null }; finish_reason: string }[];
  usage?: { prompt_tokens: number; completion_tokens: number; extra?: { prefill_tokens_per_s?: number; decode_tokens_per_s?: number } };
}

/** The embedding model for memory by meaning: 33M parameters, 384 numbers per text (the id is the runtime's). */
export const MEMORY_MODEL = "snowflake-arctic-embed-s-q0f32-MLC-b4";
export const MEMORY_DOWNLOAD_MB = 130;

interface EmbeddingEngine {
  embeddings: { create(body: { input: string[]; model?: string }): Promise<{ data: { index: number; embedding: number[] }[] }> };
}

function toBase64(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(out);
}

/** Vectors as the engine reads them: little-endian float32, base64. */
export function packVectors(rows: ArrayLike<number>[]): Vectors {
  const dims = rows[0]?.length ?? 0;
  const flat = new Float32Array(rows.length * dims);
  rows.forEach((row, i) => flat.set(row, i * dims));
  return { data: toBase64(new Uint8Array(flat.buffer)), count: rows.length };
}

let memoryLoading: Promise<void> | null = null;

/**
 * Download (once) and start the embedding model, in a worker of its own, so the residents can
 * search their memory by meaning. Resolves when it is ready; rejects where it cannot run.
 */
export function loadMemory(onProgress: (fraction: number, text: string) => void = () => undefined, test = false): Promise<void> {
  if (tabTown.embedder) return Promise.resolve();
  if (test) {
    // not a model: stand-in vectors from the engine, to exercise the page's plumbing
    tabTown.embedder = async (need) => {
      const [data, count] = await tabTown.scriptedVectors(need.key);
      return { data, count };
    };
    return Promise.resolve();
  }
  memoryLoading ??= (async () => {
    const webllm = await import("@mlc-ai/web-llm");
    const worker = new Worker(new URL("./llm.worker.ts", import.meta.url), { type: "module" });
    const engine = (await webllm.CreateWebWorkerMLCEngine(worker, MEMORY_MODEL, {
      initProgressCallback: (p: { progress: number; text: string }) => onProgress(p.progress, p.text),
    })) as unknown as EmbeddingEngine;
    // One text per forward pass: in a padded batch a text's vector shifts with its neighbours'
    // lengths, and a memory's vector must depend on the memory alone.
    const embed = async (texts: string[]): Promise<number[][]> => {
      const rows: number[][] = [];
      for (const text of texts) rows.push((await engine.embeddings.create({ input: [text] })).data[0].embedding);
      return rows;
    };
    tabTown.embedder = async (need: Need): Promise<Vectors> => {
      let texts = need.texts ?? [];
      for (let attempt = 0; ; attempt++) {
        try {
          return packVectors(await embed(texts));
        } catch (e) {
          // a text longer than the model's window: shorten and ask again (the start of a memory says what it is)
          if (attempt >= 3) throw e;
          const longest = Math.max(...texts.map((t) => t.length));
          texts = texts.map((t) => t.slice(0, Math.max(80, Math.floor(longest / 2))));
        }
      }
    };
  })().catch((e) => {
    memoryLoading = null;
    throw e;
  });
  return memoryLoading;
}
tabTown.memoryLoader = () => loadMemory();

/** Speeds the model reported for its last answers (tokens per second), for the curious. */
export const speed = { prefill: 0, decode: 0, answers: 0, seconds: 0 };

/**
 * Download (once; the browser keeps it) and start a model, then answer the residents' questions
 * with it. `onProgress` gets 0..1 and the runtime's own description of what it is doing.
 */
export async function loadMind(model: string | null, onProgress: (fraction: number, text: string) => void): Promise<void> {
  tabTown.interrupter = null;
  if (!model) {
    tabTown.answerer = null;
    return;
  }
  if (model === "test") {
    // not a model: answers with the offline fixture after a pause, to exercise the page's plumbing
    tabTown.answerer = async (need) => {
      await new Promise((r) => setTimeout(r, 15));
      return { text: await tabTown.scripted(need.key), finish: "stop", latencyMs: 15 };
    };
    return;
  }
  const webllm = await import("@mlc-ai/web-llm");
  const worker = new Worker(new URL("./llm.worker.ts", import.meta.url), { type: "module" });
  const engine = (await webllm.CreateWebWorkerMLCEngine(worker, model, {
    initProgressCallback: (p: { progress: number; text: string }) => onProgress(p.progress, p.text),
  })) as unknown as Engine;
  tabTown.interrupter = () => void engine.interruptGenerate();
  let schemaWorks = true;
  tabTown.answerer = async (need: Need): Promise<Answer> => {
    const started = performance.now();
    const body = (withSchema: boolean): Record<string, unknown> => ({
      messages: [
        { role: "system", content: need.system },
        { role: "user", content: need.prompt },
      ],
      max_tokens: need.max_tokens,
      temperature: need.temperature ?? 0.7,
      // the answer is decoded inside the task's JSON schema, so it always parses
      response_format: withSchema ? { type: "json_object", schema: JSON.stringify(need.schema) } : { type: "json_object" },
      ...(model.startsWith("Qwen3") ? { extra_body: { enable_thinking: false } } : {}),
    });
    let out: Completion;
    try {
      out = await engine.chat.completions.create(body(schemaWorks));
    } catch (e) {
      if (!schemaWorks) throw e;
      schemaWorks = false; // a schema keyword the grammar does not know: plain JSON mode, the town validates and repairs
      out = await engine.chat.completions.create(body(false));
    }
    const choice = out.choices[0];
    const latencyMs = performance.now() - started;
    speed.answers++;
    speed.seconds += latencyMs / 1000;
    speed.prefill = out.usage?.extra?.prefill_tokens_per_s ?? speed.prefill;
    speed.decode = out.usage?.extra?.decode_tokens_per_s ?? speed.decode;
    return {
      text: choice.message.content ?? "",
      inputTokens: out.usage?.prompt_tokens,
      outputTokens: out.usage?.completion_tokens,
      finish: choice.finish_reason === "length" ? "length" : "stop",
      latencyMs,
    };
  };
}
