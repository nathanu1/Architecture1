// After `vite build --mode tab`: put next to the page everything the town needs to run in a tab
// with no server and no CDN: the Python runtime (Pyodide), the three packages the engine uses,
// and the engine itself as a wheel (with its configs, prompts and scenarios inside).
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide } from "pyodide";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const repo = path.resolve(frontend, "..");
const dist = path.join(frontend, "dist-tab");
const runtime = path.join(frontend, "node_modules", "pyodide");
const out = path.join(dist, "pyodide");
fs.mkdirSync(out, { recursive: true });

// Loading the packages once under Node downloads their wheels into node_modules/pyodide.
const py = await loadPyodide();
await py.loadPackage(["numpy", "pydantic", "pyyaml"], { messageCallback: () => {} });
const lock = JSON.parse(fs.readFileSync(path.join(runtime, "pyodide-lock.json"), "utf8"));
const entry = (name) => lock.packages[name] ?? lock.packages[name.replace(/_/g, "-")] ?? lock.packages[name.replace(/-/g, "_")];
const wanted = new Set(["numpy", "pydantic", "pyyaml"]);
for (const name of wanted) for (const dep of entry(name)?.depends ?? []) wanted.add(dep);
const wheels = [...new Set([...wanted].map((n) => entry(n)?.file_name).filter(Boolean))];
const files = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json", ...wheels];
let bytes = 0;
for (const f of files) {
  fs.copyFileSync(path.join(runtime, f), path.join(out, f));
  bytes += fs.statSync(path.join(out, f)).size;
}

// The engine: build the wheel and drop what a tab never uses (the server's own copy of the page).
const tmp = fs.mkdtempSync(path.join(dist, ".wheel-"));
execFileSync("uv", ["build", "--wheel", "-o", tmp, "-q"], { cwd: repo, stdio: "inherit" });
const wheel = fs.readdirSync(tmp).find((f) => f.endsWith(".whl"));
fs.copyFileSync(path.join(tmp, wheel), path.join(dist, "hearthside.whl"));
fs.rmSync(tmp, { recursive: true, force: true });
bytes += fs.statSync(path.join(dist, "hearthside.whl")).size;

fs.renameSync(path.join(dist, "tab.html"), path.join(dist, "index.html"));
fs.writeFileSync(path.join(dist, ".nojekyll"), "");
console.log(`tab build ready in ${path.relative(repo, dist)}: runtime and engine ${(bytes / 1e6).toFixed(1)} MB (${files.length + 1} files)`);
