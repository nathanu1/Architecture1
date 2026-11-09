# Running the town as a website, with a local model and all the residents

This page is the plan for turning Hearthside into something people open in a browser: a town
that keeps living, with every resident, driven by a model on hardware you control. It starts
with what the numbers allow, then gives the simplest setup that meets them, then the
alternatives.

## 1. What the town costs to run

Everything below comes from the recorded runs in this repository.

| Fact | Value | Source |
| --- | --- | --- |
| Model calls per resident per simulated hour | about 29 | ten residents, one day (experiment B) |
| Calls per simulated hour with all 25 residents | about 730 | 29 × 25 |
| Share of calls that are mechanical (choose a location, rate importance, ground an action) | 75% | the same run's call ledger |
| Share that needs judgment (plans, reflections, dialogue, reactions) | 25% | same |
| Prompt size | about 2,500 tokens in, 30–300 out | manifests |
| Calls per step | sequential: the engine makes one call at a time | engine design (snapshot, decide, commit) |

What this means: the town's speed is the model's time per call, times about 730 per game hour.
Two things cut that down a lot, and both are already supported:

* **Two models.** Send the mechanical 75% to a small model (Llama 3.2 3B answers these in a
  fraction of a second on a GPU) and keep the 25% that needs judgment on a bigger one
  (`providers.llm.task_overrides`, set in `configs/town_n25_server.yaml`).
* **Fewer calls per hour.** `planning.decompose=false` (the hourly-only planner) removed about
  a quarter of the calls in experiment C with no change in adaptation; `architecture.reflection=false`
  removes about 12%. Both are research ablations, so use them knowingly.

Rough speeds for the full 25-resident town (estimates from measured call counts and typical
per-call latencies; measure your own with `ga doctor` and a one-hour slice):

| Hardware | Models | Real time per game hour |
| --- | --- | --- |
| One consumer or cloud GPU with 24 GB (RTX 3090/4090, L4, A10G) | 3B mechanical + 8B judgment | about 15–30 min, i.e. faster than real time |
| Apple Silicon laptop with 16–32 GB (Metal) | 3B + 8B | about 40–90 min |
| Four CPU cores, no GPU | 3B only | several hours (the documented run: 2.25 game hours in 4.8 h of model time) |
| Hosted Llama API (not local) | 70B | a few minutes, limited by rate limits; paid per token |

A town that runs "at real time" is a good target for a website: it is always doing something
when someone looks, and a game day costs one real day of GPU time.

## 2. The simplest setup that meets the goal

One Linux machine with an NVIDIA GPU (24 GB is comfortable; 12 GB works with the 3B model
alone), Docker, and a DNS name. Everything runs from this repository:

```bash
git clone https://github.com/nathanu1/Architecture1.git hearthside && cd hearthside
```

```bash
cp .env.example .env    # then set HEARTHSIDE_PASSWORD=... (and HEARTHSIDE_SPECTATORS=1 for a public page)
```

```bash
docker compose --profile ollama up -d
```

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

```bash
docker compose exec ollama ollama pull nomic-embed-text
```

Then start the full town against that Ollama (the compose file's `town` service reads these
variables from `.env`):

```
TOWN_CONFIG=configs/town_n25_server.yaml
TOWN_ARGS=--set providers.llm.base_url=http://ollama:11434 --set providers.embeddings.base_url=http://ollama:11434
```

```bash
docker compose up -d --force-recreate town
```

The town is at `http://<machine>:8080`, the research inspector at `/inspector`. For HTTPS,
run Caddy with `deploy/Caddyfile` (one reverse-proxy line; it fetches the certificate itself).
The town saves every five game minutes; `docker compose restart town` resumes the same run,
and the `/data` volume keeps it. On an NVIDIA machine, uncomment the four `deploy:` lines under
`ollama` in `docker-compose.yml` after installing the NVIDIA Container Toolkit, otherwise Ollama
runs on the CPU.

**Access.** `HEARTHSIDE_PASSWORD` gates everything with HTTP Basic auth (the browser asks once).
`HEARTHSIDE_SPECTATORS=1` opens reading to everyone: visitors watch the town and its inspector,
and chatting, building, whispering and the clock controls ask for the password. That is the
mode for a public page: one living town, one owner.

Without Docker, the same thing by hand on the machine: install Ollama, pull the three models,
`uv sync --extra viewer`, set the two variables, and run
`ga play --config configs/town_n25_server.yaml --host 0.0.0.0` (plus `--resume runs/<id>` later).

## 2b. Free: Ollama on a machine you already own, reached through a free tunnel

Ollama costs nothing; what costs money is a machine that stays on. The free way is to use one
you already have (a desktop with a GPU, a Mac with Apple Silicon, or the laptop while it is
open) and expose port 8080 with a free tunnel. Nothing changes in the town; only who can reach it.

**Cloudflare Tunnel** (free, gives you `https://<random>.trycloudflare.com` with no account, or
a name under your own domain with a free account):

```bash
ga play --config configs/town_n25_server.yaml --host 127.0.0.1      # with HEARTHSIDE_PASSWORD set
```

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

**Tailscale Funnel** (free for personal use; HTTPS under `<machine>.<tailnet>.ts.net`):

```bash
tailscale funnel 8080
```

**ngrok** works the same way (`ngrok http 8080`); its free tier shows an interstitial page.

Set `HEARTHSIDE_PASSWORD` and `HEARTHSIDE_SPECTATORS=1` before exposing anything: visitors
watch, you act. Close the tunnel with Ctrl+C; `ga play --resume runs/<id>` continues the same
town next time. On a Mac, `caffeinate -i ga play ...` keeps the laptop from sleeping while it
runs, and the town pauses itself when the end time is reached or the lid closes (a resume
continues it).

What this gives, honestly:

* **A desktop with an NVIDIA GPU or a Mac with 16 GB or more** runs the two-model 25-resident
  town at or near real time, for free, as long as the machine is on. This is the best match
  for "free, all residents, Ollama".
* **The MacBook Air** runs it, but a 25-resident game hour takes one to two real hours with
  the 3B+8B pair (the 3B alone is faster and cruder). Three to ten residents feel live on it.
* **Free cloud tiers** (Oracle Cloud's always-free Arm VM with 4 cores and 24 GB, no GPU) can
  host the town plus Ollama, but CPU inference on a 3B model is several times slower than real
  time for 25 residents; it suits a 5-resident town or a town that advances slowly in the
  background. Free GPU notebooks (Colab, Kaggle) are not persistent and cannot host a website.

**Always online without a machine on: publish the recording.** Record the full town on your
own machine whenever it is on (`ga play --config configs/town_n25_server.yaml` or `ga run`),
then export it as a static page and host it anywhere free (GitHub Pages, Cloudflare Pages,
Netlify):

```bash
cd frontend && npm run build:demo && cd ..
```

```bash
ga export-demo --run-dir runs/<id> --out frontend/dist-demo
```

The page replays the recorded town in the browser with the research inspector (Decisions,
Network, Behavior, Beliefs at their final state) and needs no server and no model; nobody can
act in it. Update it by recording more and exporting again. A good free combination is a
public recorded town that is always online plus a tunnel to the live one when your machine is
on.

## 3. Alternatives, and when to pick them

| Option | When | What changes |
| --- | --- | --- |
| **Hosted Llama through an API** (`configs/town_llama_api.yaml`; Together, Groq, OpenRouter, Fireworks) | No GPU, want 70B quality, fine with per-token cost | The town runs on a $5 VPS or even the laptop; the model is not local. About 2.8M input tokens per five-resident two-day run; multiply by five for the full town, then by the provider's price per token. `response_format: json_object` for broad compatibility. |
| **Cloud GPU rental** (RunPod, Lambda, Vast.ai, AWS g5/g6, GCP L4) | Local model, no hardware at home | Same compose file; the machine costs roughly a dollar an hour while it runs, so pause the town (`--paused`, or stop the container) when nobody is watching. |
| **Your laptop, exposed with a tunnel** (Tailscale Funnel, Cloudflare Tunnel, ngrok) | Trying it with friends before buying anything | `ga play --config configs/town_n25_server.yaml --host 127.0.0.1` behind the tunnel; speed as in the table above. |
| **Fewer residents live, all residents recorded** | GPU time is scarce | Run `town_n10_mock`/`town_ollama` live for visitors, and run the 25-resident town headless overnight (`ga run`), then publish it with `ga play --watch` or the static demo (`ga export-demo`, no server at all). |
| **Static demo page** (`npm run build:demo`, `ga export-demo`) | A page that needs no server | Visitors replay a recorded town in the browser, inspector included; nobody can act. |

What to avoid: serverless hosts (Vercel, Netlify, Cloud Run with scale-to-zero). The town is one
long-running process with a SQLite database and a background engine thread; it needs a machine
that stays up and a disk that persists.

## 4. Keeping it alive and honest

* **Resume, not restart.** The town checkpoints every 30 steps (five game minutes). A crash or
  a redeploy loses at most that; `--resume` continues from the checkpoint and re-uses recorded
  calls, so nothing is paid twice.
* **Budget ceilings.** `budget.max_calls`, `max_runtime_s` and `max_cost_usd` stop a run at its
  last checkpoint instead of spending without limit; local models record a cost of zero.
* **Labels.** The HUD says which model runs the residents and marks mock runs; the inspector
  shows the served model and every call. Keep them on a public page.
* **One town per process.** `ga play` runs one simulation. Several visitors can watch and act
  on the same town; for several towns, run several containers on different ports.
* **Replay and research.** A running town is a research run: `ga serve --run-dir /data/town`
  (or the inspector) analyses it live, every experiment metric runs on its snapshots, and
  `ga replay` reproduces it from the ledger with no model calls.

## 5. What would make it faster still

The engine makes its calls one after another. Within a step every resident decides against the
same frozen snapshot, so their calls are independent until conversations are resolved; running
the per-resident decisions on a thread pool against a batching server (vLLM, or Ollama with
`OLLAMA_NUM_PARALLEL`) could bring the full town close to the speed of the three-resident one.
It touches the engine's transaction model (one SQLite connection per step), so it is proposed,
not done; everything in this page works with the sequential engine.
