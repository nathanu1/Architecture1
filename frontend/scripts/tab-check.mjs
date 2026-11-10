// The town's engine inside the browser's Python runtime, checked under Node (no browser needed):
// a scripted town, then a town that pauses for every model answer. `npm run test:tab`.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "hearthside-wheel-"));
execFileSync("uv", ["build", "--wheel", "-o", tmp, "-q"], { cwd: repo, stdio: "inherit" });
const wheel = path.join(tmp, fs.readdirSync(tmp).find((f) => f.endsWith(".whl")));

const py = await loadPyodide();
await py.loadPackage(["numpy", "pydantic", "pyyaml"], { messageCallback: () => {} });
py.unpackArchive(new Uint8Array(fs.readFileSync(wheel)), "wheel");
const out = JSON.parse(
  await py.runPythonAsync(`
import json, time
from generative_agents.game.tab import TabTown
t = time.time()
SEVEN = "scenario.start=2023-02-13T07:00:00"  # a fixed opening hour, so the step counts below are known
town = TabTown("/town/scripted", mind="scripted", overrides=[SEVEN, "scenario.end=2023-02-13T08:00:00"], speed="max")
while not town.session.finished:
    town.tick()
scripted = {"steps": town.sim.clock.step, "seconds": round(time.time() - t, 2)}
info = json.loads(town.call("info"))["ok"]
poll = json.loads(town.call("poll", "[-2, 0]"))["ok"]
memories = json.loads(town.call("research", json.dumps(["agent/" + info["residents"][0]["id"] + "/memories?limit=3"])))["ok"]
town.close()
t = time.time()
live = TabTown("/town/model", mind="some-model", overrides=[SEVEN, "scenario.end=2023-02-13T07:30:00"], speed="max")
needs = batches = 0
while not live.session.finished:
    r = live.tick()
    if "need" in r and r["need"].get("kind") == "embed":
        batches += 1
        live.deliver_vectors(r["need"]["key"], *live.scripted_vectors(r["need"]["key"]))
    elif "need" in r:
        needs += 1
        live.deliver(r["need"]["key"], live.scripted_answer(r["need"]["key"]))
stats = live.stats()
json.dumps({"scripted": scripted, "residents": len(info["residents"]), "frames": len(poll["frames"]), "memories": len(memories),
            "questions": needs, "repeated_steps": live.repeats, "seconds": round(time.time() - t, 2), "steps": live.sim.clock.step,
            "memory": live.info()["memory"], "vector_batches": batches, "vectors": stats["embedded"], "error": live.session.error})
`),
);
console.log(out);
const ok = out.scripted.steps === 360 && out.residents === 3 && out.frames > 300 && out.memories === 3 && out.questions > 5 && out.questions + out.vector_batches === out.repeated_steps && out.steps === 180 && out.memory === "meaning" && out.vectors > out.vector_batches && !out.error;
fs.rmSync(tmp, { recursive: true, force: true });
if (!ok) {
  console.error("the town did not run as expected inside Pyodide");
  process.exit(1);
}
console.log("ok: the town runs inside the browser's Python runtime, with and without pausing for a model and for its memory's vectors");
