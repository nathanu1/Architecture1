import type { Api } from "../api";
import type { BuildCheck, BuildOp, Info, MapPayload, Poll, ResidentDetail } from "../types";
import { tabTown } from "./client";

/** The same interface the server offers, answered by the engine running in this tab. */
export const tabApi: Api = {
  info: () => tabTown.call<Info>("info"),
  map: () => tabTown.call<MapPayload>("map"),
  poll: (sinceStep: number, sinceFeed: number) => tabTown.call<Poll>("poll", sinceStep, sinceFeed),
  action: (kind: string, payload: Record<string, unknown>) => tabTown.call<{ seq: number; step: number }>("action", kind, payload),
  validateBuild: (ops: BuildOp[]) => tabTown.call<BuildCheck>("validate_build", ops),
  control: (action, speed) => tabTown.call<{ paused: boolean; speed: string; status: string }>("control", action, speed ?? null),
  resident: (id: string) => tabTown.call<ResidentDetail>("resident", id),
  object: (address: string) => tabTown.call<{ address: string; name: string; place: string[]; search_theme: string | null }>("object", address),
  research: <T>(path: string) => tabTown.call<T>("research", path),
};
