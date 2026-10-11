import { listOf } from "../lib/text";
import type { Info } from "../types";

const SERVERS: Record<string, string> = { ollama: "Ollama", openai_compatible: "a local model server" };

/** Who wrote the residents' words in a recording, from what `ga export-demo` stored with it. */
export function recordedWith(info: Info): { mock: boolean; model: string; via: string | null } {
  const [kind, ...rest] = (info.recording?.model ?? `${info.llm.kind}:${info.llm.model}`).split(":");
  return { mock: kind === "mock" || info.recording?.mode === "mock", model: rest.join(":") || info.llm.model, via: SERVERS[kind] ?? null };
}

const DOING: [string, string][] = [
  ["chat", "chats with them"],
  ["gift", "gives a gift"],
  ["build", "builds"],
  ["delivered", "grants a wish"],
  ["whisper", "speaks as an inner voice"],
];

/** "chats with them, gives a gift and builds": what the player did in the recording, in order of kind. */
export function playerDid(kinds: Iterable<string>): string | null {
  const seen = new Set(kinds);
  const parts = DOING.filter(([kind]) => seen.has(kind)).map(([, text]) => text);
  return parts.length ? listOf(parts) : null;
}

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
/** "Three residents", "25 residents". */
export const residentsWord = (n: number) => `${WORDS[n] ?? n} resident${n === 1 ? "" : "s"}`;
