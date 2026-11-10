/// <reference lib="webworker" />
// The town's engine, in this tab: CPython compiled to WebAssembly (Pyodide) running the same
// Python package a server would, driven one pass at a time (generative_agents/game/tab.py).
// The page asks through messages; when the residents need the model, the worker posts the
// question and waits for the page to send the answer back.
import type { Answer, FromWorker, Need, Phase, ToWorker } from "./protocol";

declare const self: DedicatedWorkerGlobalScope;

interface PyProxy {
  call(method: string, args: string): string;
  destroy?: () => void;
}
interface Pyodide {
  loadPackage(names: string[], opts?: { messageCallback?: (m: string) => void }): Promise<void>;
  unpackArchive(buffer: ArrayBuffer | Uint8Array, format: string): void;
  runPython(code: string): unknown;
  globals: { get(name: string): unknown; set(name: string, value: unknown): void };
  FS: {
    mkdirTree(path: string): void;
    mount(fs: unknown, opts: object, path: string): void;
    syncfs(populate: boolean, done: (err: unknown) => void): void;
    filesystems: { IDBFS: unknown };
  };
}

const post = (m: FromWorker) => self.postMessage(m);
const phase = (p: Phase) => post({ type: "phase", phase: p });
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const SAVE_EVERY_MS = 20_000;

let py: Pyodide | null = null;
let town: PyProxy | null = null;
let running = false;
let lastSave = 0;
let dirty = false;
let answerWaiter: ((a: { key: string; answer?: Answer; message?: string }) => void) | null = null;

function call<T>(method: string, args: unknown[]): T {
  if (!town) throw { status: 503, detail: "the town is still waking up" };
  const out = JSON.parse(town.call(method, JSON.stringify(args))) as { ok?: T; error?: { status: number; detail: string } };
  if (out.error) throw out.error;
  return out.ok as T;
}

const syncfs = (populate: boolean) => new Promise<void>((res, rej) => py!.FS.syncfs(populate, (err) => (err ? rej(err) : res())));

async function save(): Promise<void> {
  if (!py || !dirty) return;
  dirty = false;
  lastSave = Date.now();
  try {
    await syncfs(false);
    post({ type: "saved", at: lastSave });
  } catch {
    dirty = true; // storage refused (private window, quota): the town keeps running in memory
  }
}

async function boot(base: string): Promise<void> {
  phase("runtime");
  const { loadPyodide } = (await import(/* @vite-ignore */ `${base}pyodide/pyodide.mjs`)) as { loadPyodide: (o: { indexURL: string }) => Promise<Pyodide> };
  py = await loadPyodide({ indexURL: `${base}pyodide/` });
  phase("packages");
  await py.loadPackage(["numpy", "pydantic", "pyyaml"], { messageCallback: () => undefined });
  phase("engine");
  const wheel = await fetch(`${base}hearthside.whl`);
  if (!wheel.ok) throw { status: 500, detail: "the town's engine file is missing from this site" };
  py.unpackArchive(await wheel.arrayBuffer(), "wheel");
  phase("storage");
  py.FS.mkdirTree("/town");
  try {
    py.FS.mount(py.FS.filesystems.IDBFS, {}, "/town");
    await syncfs(true);
  } catch {
    /* no storage here: the town lives until the tab closes */
  }
  py.runPython("from generative_agents.game.tab import TabTown");
  phase("ready");
}

function start(mind: string, fresh: boolean, speed: string): unknown {
  if (!py) throw { status: 503, detail: "the engine has not loaded yet" };
  running = false;
  py.globals.set("_mind", mind);
  py.globals.set("_fresh", fresh);
  py.globals.set("_speed", speed);
  py.runPython(`
import os, shutil
if globals().get("town") is not None:
    town.close()
    town = None
if _fresh and os.path.isdir("/town/run"):
    shutil.rmtree("/town/run")
town = TabTown("/town/run", mind=_mind, speed=_speed)
`);
  town = py.globals.get("town") as PyProxy;
  dirty = true;
  running = true;
  void loop();
  return call("info", []);
}

async function loop(): Promise<void> {
  const mine = town;
  while (running && town === mine) {
    let r: { need?: Need; wait?: number };
    try {
      r = call("tick", []);
    } catch (e) {
      console.error("town tick failed", e);
      await sleep(1000);
      continue;
    }
    dirty = true;
    if (r.need) {
      const need = r.need;
      post({ type: "need", need });
      const got = await new Promise<{ key: string; answer?: Answer; message?: string }>((res) => (answerWaiter = res));
      answerWaiter = null;
      if (town !== mine) return;
      if (got.answer) call("deliver", [need.key, got.answer.text, got.answer.inputTokens ?? null, got.answer.outputTokens ?? null, got.answer.finish, got.answer.latencyMs]);
      else call("fail", [need.key, got.message ?? "no answer"]);
      continue;
    }
    if (Date.now() - lastSave > SAVE_EVERY_MS) await save();
    await sleep(Math.max(0, (r.wait ?? 0) * 1000)); // also lets the page's questions in between passes
  }
}

self.onmessage = async (ev: MessageEvent<ToWorker>) => {
  const m = ev.data;
  if (m.type === "answer") return answerWaiter?.({ key: m.key, answer: m.answer });
  if (m.type === "fail") return answerWaiter?.({ key: m.key, message: m.message });
  try {
    let ok: unknown = null;
    if (m.type === "boot") await boot(m.base);
    else if (m.type === "start") ok = start(m.mind, m.fresh, m.speed);
    else if (m.type === "call") ok = call(m.method, m.args);
    else if (m.type === "save") {
      dirty = true;
      await save();
    } else if (m.type === "stop") {
      running = false;
      await save();
    }
    post({ id: m.id, ok });
  } catch (e) {
    const err = e as { status?: number; detail?: string; message?: string };
    post({ id: m.id, error: { status: err.status ?? 500, detail: err.detail ?? err.message ?? String(e) } });
  }
};
