/** A chip on the recording's timeline: where to jump and what happens there. */
export interface Moment {
  step: number;
  label: string;
}

interface Event {
  step: number;
  kind: string;
  agent_id?: unknown;
  participants?: unknown;
  name?: unknown;
}

/** Events this close (ten game minutes) and of the same sort share one chip. */
const BURST = 60;

/**
 * The moments worth a chip, oldest first. In a big town many things happen at once, so a burst of
 * the same sort (residents' conversations, wishes coming true, builds), even interleaved with other
 * sorts, becomes one chip with a count, which jumps to the first of them; the Town Pulse chip shows
 * the newest level; the player's chats, gifts and whispers keep one chip per resident.
 */
export function momentsOf(events: readonly Event[], name: (id: unknown) => string): Moment[] {
  type Chip = Moment & { last: number; n: number; one: string };
  const out: Chip[] = [];
  const open = new Map<string, Chip>(); // the latest chip of each sort, joined while its burst lasts
  for (const e of events) {
    const one = single(e, name);
    if (!one) continue;
    const key = ["chat", "gift", "whisper"].includes(e.kind) ? `${e.kind}:${String(e.agent_id)}` : e.kind;
    const chip = open.get(key);
    if (chip && e.step - chip.last < BURST) {
      chip.n += 1;
      chip.last = e.step;
      chip.label = e.kind === "level_up" ? one : (many(e.kind, chip.n) ?? chip.one);
      continue;
    }
    const fresh = { step: e.step, label: one, last: e.step, n: 1, one };
    out.push(fresh);
    open.set(key, fresh);
  }
  return out.map(({ step, label }) => ({ step, label }));
}

function single(e: Event, name: (id: unknown) => string): string | null {
  switch (e.kind) {
    case "chat":
      return `You chat with ${name(e.agent_id)}`;
    case "gift":
      return `A gift for ${name(e.agent_id)}`;
    case "request":
      return "Residents make wishes";
    case "build":
      return "You build";
    case "delivered":
      return `${name(e.agent_id)}’s wish comes true`;
    case "level_up":
      return `Town Pulse: ${String(e.name ?? "level up")}`;
    case "conversation":
      return `${((e.participants as string[]) ?? []).map(name).join(" and ")} talk`;
    case "whisper":
      return `Inner voice for ${name(e.agent_id)}`;
    default:
      return null;
  }
}

function many(kind: string, n: number): string | null {
  switch (kind) {
    case "conversation":
      return `${n} conversations`;
    case "delivered":
      return `${n} wishes come true`;
    case "build":
      return `You build ${n} things`;
    default:
      return null; // the same label: "Residents make wishes", or the same resident again
  }
}
