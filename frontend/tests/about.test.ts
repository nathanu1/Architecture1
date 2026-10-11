import { describe, expect, it } from "vitest";
import { modelWrote, partOfDay, playerDid, recordedWith, residentsWord } from "../src/demo/about";
import { openingStep } from "../src/demo/api";
import type { Timeline } from "../src/demo/player";
import type { Info } from "../src/types";

const info = (recording: Info["recording"], llm = { kind: "replay", model: "replay" }) => ({ llm: { ...llm, local: false, describe: {} }, recording }) as unknown as Info;

describe("what a recording says about itself", () => {
  it("names the model that wrote the residents' words, and flags the mock", () => {
    expect(recordedWith(info({ source_run: "town-mock", mode: "mock", model: "mock:mock-llm-v1" }))).toEqual({ mock: true, model: "mock-llm-v1", via: null });
    expect(recordedWith(info({ source_run: "town-ollama", mode: "live", model: "ollama:llama3.2:3b" }))).toEqual({ mock: false, model: "llama3.2:3b", via: "Ollama" });
    // an older export without the recording block falls back to the replayed config
    expect(recordedWith(info(undefined, { kind: "mock", model: "mock-llm-v1" })).mock).toBe(true);
  });

  it("lists what the player did once each, in a fixed order", () => {
    const list = new Intl.ListFormat(undefined, { style: "long", type: "conjunction" });
    expect(playerDid(["chat", "build", "chat", "conversation", "gift"])).toBe(list.format(["chats with them", "gives a gift", "builds"]));
    expect(playerDid(["conversation", "request"])).toBeNull();
    expect(residentsWord(3)).toBe("Three residents");
    expect(residentsWord(25)).toBe("25 residents");
  });

  it("claims only what the recording contains", () => {
    const list = new Intl.ListFormat(undefined, { style: "long", type: "conjunction" });
    // no resident-to-resident conversation happened, so none is claimed
    expect(modelWrote(["chat", "request", "whisper"])).toBe(list.format(["plans", "wishes", "replies"]));
    expect(modelWrote(["conversation"])).toBe(list.format(["plans", "conversations"]));
    expect([partOfDay(7, 13), partOfDay(7, 17.98), partOfDay(13, 18)]).toEqual(["morning", "day", "afternoon"]);
  });

  it("opens fifteen game minutes before the player's first action, never before the start", () => {
    const tl = (feed: { step: number; kind: string }[]) => ({ frames: [[0], [2000]], feed }) as unknown as Timeline;
    expect(openingStep(tl([{ step: 0, kind: "welcome" }, { step: 220, kind: "conversation" }, { step: 390, kind: "chat" }]))).toBe(300);
    expect(openingStep(tl([{ step: 0, kind: "chat" }]))).toBe(0);
    expect(openingStep(tl([{ step: 50, kind: "request" }]))).toBe(0); // residents' own wishes are not the player's
  });
});
