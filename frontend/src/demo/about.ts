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

/** "plans, wishes and replies": what the model wrote in a recording, naming only what happened in it. */
export function modelWrote(kinds: Iterable<string>): string {
  const seen = new Set(kinds);
  const parts = ["plans", seen.has("request") ? "wishes" : "", seen.has("chat") ? "replies" : "", seen.has("conversation") ? "conversations" : ""];
  return listOf(parts.filter(Boolean));
}

/** "morning" for a recording that ends by 1 PM, "afternoon" for one that starts after noon, else "day". */
export function partOfDay(startHour: number, endHour: number): string {
  return endHour <= 13 ? "morning" : startHour >= 12 ? "afternoon" : "day";
}

const WORDS = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten"];
/** "Three residents", "25 residents". */
export const residentsWord = (n: number) => `${WORDS[n] ?? n} resident${n === 1 ? "" : "s"}`;
