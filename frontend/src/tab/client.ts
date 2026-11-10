import { ApiError } from "../apiError";
import type { Answer, FromWorker, Need, Phase, ToWorker, Vectors } from "./protocol";

type Pending = { resolve: (v: unknown) => void; reject: (e: Error) => void };

/**
 * The page's side of the town in this tab: starts the engine worker, forwards the interface's
 * requests to it, and hands the residents' questions to whichever mind is plugged in.
 */
class TabTownClient {
  private worker: Worker | null = null;
  private pending = new Map<number, Pending>();
  private seq = 0;
  private booted: Promise<void> | null = null;
  private started: Promise<unknown> | null = null;
  private startedResolve: ((v: unknown) => void) | null = null;
  /** Answers a question from the residents (set by the mind that is plugged in). */
  answerer: ((need: Need) => Promise<Answer>) | null = null;
  /** Stops the answer in progress, if the mind can (set by the mind that is plugged in). */
  interrupter: (() => void) | null = null;
  /** Turns texts into vectors for memory by meaning (set once the embedding model is loaded). */
  embedder: ((need: Need) => Promise<Vectors>) | null = null;
  /** Loads the embedding model when a town that needs it is opened without it. */
  memoryLoader: (() => Promise<void>) | null = null;
  embedded = 0;
  private thinkingAbout: Need | null = null;
  private setAside = false;
  onPhase: ((p: Phase) => void) | null = null;
  onNeed: ((need: Need | null) => void) | null = null;
  phase: Phase | null = null;
  asked = 0;

  /** Resolves once a town is running; the interface's first requests wait on it. */
  readonly ready: Promise<unknown> = new Promise((res) => (this.startedResolve = res));

  private send<T>(m: Record<string, unknown>): Promise<T> {
    const id = ++this.seq;
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
      this.worker!.postMessage({ ...m, id } as ToWorker);
    });
  }

  /** Load the engine (starts on page load, so the click that starts the town does not wait for it). */
  boot(): Promise<void> {
    if (this.booted) return this.booted;
    this.worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.worker.onmessage = (ev: MessageEvent<FromWorker>) => this.receive(ev.data);
    this.worker.onerror = (ev) => {
      for (const p of this.pending.values()) p.reject(new ApiError(500, ev.message || "the town's engine stopped"));
      this.pending.clear();
    };
    const base = new URL("./", window.location.href).href;
    this.booted = this.send<void>({ type: "boot", base });
    return this.booted;
  }

  private receive(m: FromWorker): void {
    if ("type" in m) {
      if (m.type === "phase") {
        this.phase = m.phase;
        this.onPhase?.(m.phase);
      } else if (m.type === "need") void this.think(m.need);
      return;
    }
    const p = this.pending.get(m.id);
    if (!p) return;
    this.pending.delete(m.id);
    if ("error" in m) p.reject(new ApiError(m.error.status, m.error.detail));
    else p.resolve(m.ok);
  }

  /** Memory by meaning: the texts of one pass become vectors in one batch. No one is "thinking". */
  private async embed(need: Need): Promise<void> {
    try {
      if (!this.embedder) await this.memoryLoader?.();
      if (!this.embedder) throw new Error("this town remembers by meaning, and its memory model could not be loaded here");
      const vectors = await this.embedder(need);
      this.embedded += vectors.count;
      this.worker!.postMessage({ type: "vectors", key: need.key, vectors } as ToWorker);
    } catch (e) {
      this.worker!.postMessage({ type: "fail", key: need.key, message: (e as Error).message || String(e) } as ToWorker);
    }
  }

  private async think(need: Need): Promise<void> {
    if (need.kind === "embed") return this.embed(need);
    this.asked++;
    this.onNeed?.(need);
    this.thinkingAbout = need;
    this.setAside = false;
    try {
      if (!this.answerer) throw new Error("no mind is loaded");
      const answer = await this.answerer(need);
      if (this.setAside) this.worker!.postMessage({ type: "skip", key: need.key } as ToWorker);
      else this.worker!.postMessage({ type: "answer", key: need.key, answer } as ToWorker);
    } catch (e) {
      if (this.setAside) this.worker!.postMessage({ type: "skip", key: need.key } as ToWorker);
      else this.worker!.postMessage({ type: "fail", key: need.key, message: (e as Error).message || String(e) } as ToWorker);
    } finally {
      this.thinkingAbout = null;
      this.onNeed?.(null);
    }
  }

  /** Found the town (or continue the one saved in this browser) with the given mind. */
  async start(mind: string, opts: { fresh?: boolean; speed?: string; residents?: number; depth?: string; memory?: string } = {}): Promise<void> {
    await this.boot();
    this.started = this.send({
      type: "start",
      mind,
      fresh: !!opts.fresh,
      speed: opts.speed ?? "normal",
      residents: opts.residents ?? 10,
      depth: opts.depth ?? "mind",
      memory: opts.memory ?? "words",
    });
    this.startedResolve?.(await this.started);
  }

  async call<T>(method: string, ...args: unknown[]): Promise<T> {
    await this.ready;
    // the player spoke or acted: a resident's own thought in progress steps aside for it
    if (method === "action" && this.thinkingAbout && this.thinkingAbout.task !== "player_chat" && this.interrupter) {
      this.setAside = true;
      this.interrupter();
    }
    return this.send<T>({ type: "call", method, args });
  }

  /** What the offline fixture would answer (used by the test mind to exercise the plumbing). */
  scripted(key: string): Promise<string> {
    return this.send<string>({ type: "call", method: "scripted_answer", args: [key] });
  }

  /** Stand-in vectors from the engine itself (used by the test mind to exercise the plumbing). */
  scriptedVectors(key: string): Promise<[string, number]> {
    return this.send<[string, number]>({ type: "call", method: "scripted_vectors", args: [key] });
  }

  save(): Promise<void> {
    return this.worker ? this.send<void>({ type: "save" }) : Promise.resolve();
  }
}

export const tabTown = new TabTownClient();
// for the curious (and the browser checks): the town in this tab, from the console
(globalThis as unknown as { __tabTown?: TabTownClient }).__tabTown = tabTown;
