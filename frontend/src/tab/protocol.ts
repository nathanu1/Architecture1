/** Messages between the page and the worker that runs the town's engine (Python in WebAssembly). */

/** A question the residents need answered by the model before the town can go on. */
export interface Need {
  key: string;
  /** "embed": the texts below need vectors from the embedding model; otherwise a question for the model. */
  kind?: "embed";
  texts?: string[];
  task: string;
  agent_id: string | null;
  model: string;
  system: string;
  prompt: string;
  schema: Record<string, unknown>;
  max_tokens: number;
  temperature: number | null;
}

export interface Answer {
  text: string;
  inputTokens?: number;
  outputTokens?: number;
  finish: "stop" | "length";
  latencyMs: number;
}

/** Vectors for an "embed" need: `count` of them, as base64 of their float32 numbers, in the order asked. */
export interface Vectors {
  data: string;
  count: number;
}

export type Phase = "runtime" | "packages" | "engine" | "storage" | "ready";

export type ToWorker =
  | { id: number; type: "boot"; base: string }
  | { id: number; type: "start"; mind: string; fresh: boolean; speed: string; residents: number; depth: string; memory: string }
  | { id: number; type: "call"; method: string; args: unknown[] }
  | { id: number; type: "save" }
  | { id: number; type: "stop" }
  | { type: "answer"; key: string; answer: Answer }
  | { type: "vectors"; key: string; vectors: Vectors }
  | { type: "fail"; key: string; message: string }
  | { type: "skip"; key: string };

export type FromWorker =
  | { id: number; ok: unknown }
  | { id: number; error: { status: number; detail: string } }
  | { type: "phase"; phase: Phase }
  | { type: "need"; need: Need }
  | { type: "saved"; at: number };
