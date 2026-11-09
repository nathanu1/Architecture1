import { describe, expect, it } from "vitest";
import { circleLayout, colorFor, daysOf, familiarityWord, percent, recordSummary, TOM_LABELS, valenceWord } from "../src/lib/research";

const name = (id: string) => ({ isabella_rodriguez: "Isabella Rodriguez", klaus_mueller: "Klaus Mueller" })[id] ?? id;

describe("decision record summaries", () => {
  it("describes each recorded event from its stored payload only", () => {
    expect(recordSummary({ type: "action", payload: { activity: "open the cafe", address: "the Ville:Hobbs Cafe:cafe:behind the cafe counter" } }, name)).toBe("open the cafe at Hobbs Cafe › cafe › behind the cafe counter");
    expect(recordSummary({ type: "reaction", payload: { observation: "stove is burning", decision: "react", new_activity: "put out the fire", minutes: 10, reason: "Something is burning." } }, name)).toBe(
      "Saw “stove is burning” and decided to react: put out the fire (10 min). Stated reason: Something is burning.",
    );
    expect(recordSummary({ type: "conversation", payload: { participants: ["isabella_rodriguez", "klaus_mueller"], utterances: 4, summary: "This is a conversation about a party." } }, name)).toBe(
      "Isabella Rodriguez and Klaus Mueller, 4 lines: This is a conversation about a party.",
    );
    expect(recordSummary({ type: "replan", payload: { inserted: "chat", minutes: 5, source: "conversation", displaced: [{}, {}] } }, name)).toContain("displaced 2 task(s)");
    expect(recordSummary({ type: "unknown_kind", payload: { a: 1 } }, name)).toBe('{"a":1}');
  });

  it("colors known event types and falls back for the rest", () => {
    expect(colorFor("action")).toBe("#4a82dd");
    expect(colorFor("anything")).toBe("#625f75");
  });
});

describe("network layout and words", () => {
  it("places residents evenly on a circle starting at the top", () => {
    const pos = circleLayout(["a", "b", "c", "d"], 200);
    expect(pos.a[0]).toBeCloseTo(100);
    expect(pos.a[1]).toBeCloseTo(100 - 46);
    expect(pos.c[1]).toBeCloseTo(100 + 46);
    expect(Object.keys(pos)).toHaveLength(4);
  });

  it("turns familiarity and valence into the words the records use", () => {
    expect(familiarityWord(0.7)).toBe("close");
    expect(familiarityWord(0.05)).toBe("barely known");
    expect(valenceWord(0.6)).toBe("warm");
    expect(valenceWord(-0.6)).toBe("strained");
    expect(percent(0.4567)).toBe("46%");
    expect(percent(null)).toBe("–");
  });

  it("lists the days of a record set in order and names every ToM label", () => {
    expect(daysOf([{ sim_time: "2023-02-14T09:00:00" }, { sim_time: "2023-02-13T09:00:00" }, { sim_time: "2023-02-13T10:00:00" }])).toEqual(["2023-02-13", "2023-02-14"]);
    for (const label of ["grounded_correct", "ungrounded_correct", "over_attribution", "under_attribution", "unaware_of_other", "correct_negative", "label_failed"]) expect(TOM_LABELS[label]).toBeTruthy();
  });
});
