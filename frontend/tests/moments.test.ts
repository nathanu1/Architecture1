import { describe, expect, it } from "vitest";
import { momentsOf } from "../src/demo/moments";

const name = (id: unknown) => String(id).split("_")[0].replace(/^./, (c) => c.toUpperCase());

describe("moments on the recording's timeline", () => {
  it("merges a burst of the same sort into one chip with a count", () => {
    const events = [
      { step: 0, kind: "welcome" },
      { step: 10, kind: "conversation", participants: ["mei_lin", "john_lin"] },
      { step: 40, kind: "conversation", participants: ["tom_moreno", "jane_moreno"] },
      { step: 90, kind: "conversation", participants: ["sam_moore", "jennifer_moore"] },
      { step: 400, kind: "conversation", participants: ["ayesha_khan", "wolfgang_schulz"] },
      { step: 500, kind: "delivered", agent_id: "klaus_mueller" },
      { step: 510, kind: "delivered", agent_id: "maria_lopez" },
    ];
    expect(momentsOf(events, name)).toEqual([
      { step: 10, label: "3 conversations" }, // each within ten game minutes of the last
      { step: 400, label: "Ayesha and Wolfgang talk" },
      { step: 500, label: "2 wishes come true" },
    ]);
  });

  it("joins a sort across interleaved events, like a rush of wishes, builds and deliveries", () => {
    const events = [
      { step: 720, kind: "request", agent_id: "a" },
      { step: 721, kind: "build" },
      { step: 722, kind: "delivered", agent_id: "latoya_williams" },
      { step: 722, kind: "level_up", name: "Waking Village" },
      { step: 723, kind: "request", agent_id: "b" },
      { step: 724, kind: "build" },
      { step: 725, kind: "delivered", agent_id: "rajiv_patel" },
      { step: 725, kind: "level_up", name: "Friendly Town" },
    ];
    expect(momentsOf(events, name)).toEqual([
      { step: 720, label: "Residents make wishes" },
      { step: 721, label: "You build 2 things" },
      { step: 722, label: "2 wishes come true" },
      { step: 722, label: "Town Pulse: Friendly Town" },
    ]);
  });

  it("keeps the player's chats one per resident", () => {
    const events = [
      { step: 5, kind: "chat", agent_id: "klaus_mueller" },
      { step: 8, kind: "chat", agent_id: "klaus_mueller" },
      { step: 12, kind: "chat", agent_id: "maria_lopez" },
    ];
    expect(momentsOf(events, name)).toEqual([
      { step: 5, label: "You chat with Klaus" },
      { step: 12, label: "You chat with Maria" },
    ]);
  });
});
