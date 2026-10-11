import { listOf } from "../lib/text";
import type { Info } from "../types";

const SERVERS: Record<string, string> = { ollama: "Ollama", openai_compatible: "a local model server" };

/** Who wrote the residents' words in a recording, from what `ga export-demo` stored with it. */
export function recordedWith(info: Info): { mock: boolean; model: string; via: string | null } {
  const [kind, ...rest] = (info.recording?.model ?? `${info.llm.kind}:${info.llm.model}`).split(":");
  return { mock: kind === "mock" || info.recording?.mode === "mock", model: rest.join(":") || info.llm.model, via: SERVERS[kind] ?? null };
}

const DOING: [string, (n: number) => string][] = [
  ["chat", () => "chats with them"],
  ["gift", (n) => (n === 1 ? "gives a gift" : `gives ${n} gifts`)],
  ["build", () => "builds"],
  ["delivered", (n) => (n === 1 ? "grants a wish" : `grants ${n} wishes`)],
  ["whisper", () => "speaks as an inner voice"],
];

/** "chats with them, gives 2 gifts and grants 25 wishes": what the player did, in order of kind. */
export function playerDid(kinds: Iterable<string>): string | null {
  const count = new Map<string, number>();
  for (const k of kinds) count.set(k, (count.get(k) ?? 0) + 1);
  const parts = DOING.filter(([kind]) => count.has(kind)).map(([kind, text]) => text(count.get(kind)!));
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
