// Pure helpers for the inspector's research views (decisions, network, behavior, beliefs).
// Everything here formats recorded data; nothing is inferred or explained after the fact.

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export interface DecisionRecord {
  id: number;
  step: number;
  sim_time: string;
  type: string;
  payload: Json;
  trace_ids: string[];
  call_ids: number[];
  calls_at_time?: { id: number; task: string; status: string; attempt_kind?: string }[];
}

/** Theme colors, reused as data colors so the research views match the town. */
export const RESEARCH_COLORS = {
  action: "#4a82dd",
  reaction: "#ee8a5c",
  replan: "#625f75",
  conversation: "#e2629b",
  reflection: "#9b6fd6",
  day_plan: "#2a9d96",
  intervention: "#d99a26",
  action_failure: "#b3261e",
  plan_failure: "#b3261e",
  constraint: "#b3261e",
  talk_skipped: "#625f75",
} as const;

export const colorFor = (type: string): string => (RESEARCH_COLORS as Record<string, string>)[type] ?? "#625f75";

/** One readable line per recorded event, built only from the stored payload. */
export function recordSummary(r: Pick<DecisionRecord, "type" | "payload">, name: (id: string) => string): string {
  const d = r.payload ?? {};
  switch (r.type) {
    case "action":
      return `${d.activity ?? ""}${d.address ? ` at ${String(d.address).split(":").slice(1).join(" › ")}` : ""}`;
    case "reaction":
      return `Saw “${d.observation ?? ""}” and decided to ${d.decision ?? "?"}${d.new_activity ? `: ${d.new_activity} (${d.minutes ?? "?"} min)` : ""}${d.reason ? `. Stated reason: ${d.reason}` : ""}`;
    case "replan":
      return `Inserted “${d.inserted ?? ""}” for ${d.minutes ?? "?"} min (${d.source ?? ""}); displaced ${(d.displaced ?? []).length} task(s)`;
    case "conversation":
      return `${(d.participants ?? []).map(name).join(" and ")}, ${d.utterances ?? 0} lines${d.summary ? `: ${d.summary}` : ""}`;
    case "reflection":
      return `${d.stored ?? 0} insight(s) from ${(d.questions ?? []).length} question(s)${d.failures?.length ? `, ${d.failures.length} failed` : ""}`;
    case "day_plan":
      return `Woke at ${d.wake_up_time ?? "?"}; ${(d.items ?? []).length} items in ${(d.blocks ?? []).length} hour blocks`;
    case "intervention":
      return `${d.kind ?? ""}: ${d.description ?? d.address ?? d.text ?? ""}`;
    case "action_failure":
      return `Could not do “${d.activity ?? ""}”: ${d.reason ?? ""}`;
    case "plan_failure":
      return `${d.level ?? ""} plan failed: ${d.error ?? ""}`;
    case "constraint":
      return `${d.rule ?? ""}: ${d.message ?? ""}`;
    case "talk_skipped":
      return `Did not start a conversation with ${name(d.partner ?? "")}: ${d.reason ?? ""}`;
    default:
      return JSON.stringify(d).slice(0, 120);
  }
}

/** Points on a circle for a small social graph, in node order. */
export function circleLayout(nodes: string[], size: number, margin = 54): Record<string, [number, number]> {
  const c = size / 2;
  const r = Math.max(10, size / 2 - margin);
  const out: Record<string, [number, number]> = {};
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, nodes.length) - Math.PI / 2;
    out[n] = [c + r * Math.cos(a), c + r * Math.sin(a)];
  });
  return out;
}

export const percent = (v: number | null | undefined): string => (v == null ? "–" : `${Math.round(v * 100)}%`);

export function familiarityWord(f: number): string {
  if (f >= 0.6) return "close";
  if (f >= 0.35) return "familiar";
  if (f >= 0.12) return "acquainted";
  return "barely known";
}

export function valenceWord(v: number): string {
  if (v >= 0.5) return "warm";
  if (v >= 0.15) return "friendly";
  if (v >= -0.15) return "neutral";
  if (v >= -0.5) return "cool";
  return "strained";
}

export const TOM_LABELS: Record<string, string> = {
  grounded_correct: "Right, with grounds",
  ungrounded_correct: "Right, but a guess",
  over_attribution: "Over-attributed",
  under_attribution: "Under-attributed",
  unaware_of_other: "Unaware",
  correct_negative: "Right (does not know)",
  label_failed: "Label failed",
};

/** The days a list of records spans, oldest first. */
export function daysOf(records: { sim_time: string }[]): string[] {
  return [...new Set(records.map((r) => r.sim_time.slice(0, 10)))].sort();
}
