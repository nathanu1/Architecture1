# The living town on a local model

Hearthside has two paths. This page is the first one: **a town that stays on, driven by a Llama
you serve yourself**, reachable as an app, from a server, or as a site. The second path is the
[research platform](research_platform.md), which studies the same town. The reasoning and the
order of work are in [plan.md](plan.md).

## 1. The shape

```
 browsers, phones, the installed app
              │  HTTPS (Caddy or a tunnel), password to act, anyone may watch
              ▼
 ┌───────────────────────────┐        HTTP         ┌──────────────────────────────┐
 │ the town  (ga town)       │ ──────────────────▶ │ the model server             │
 │ Python + SQLite, one      │  HEARTHSIDE_LLM_URL │ Ollama, llama.cpp or vLLM    │
 │ process, any machine      │                     │ the only part that needs     │
 │ engine · ledger · web UI  │ ◀────────────────── │ a GPU or many cores          │
 └───────────────────────────┘                     └──────────────────────────────┘
        runs/<town name>/  (state, call ledger, config: copy this folder to move the town)
```

The town process has no hardware requirements: it is plain Python and SQLite and runs on any
architecture Python runs on. Everything heavy sits behind one HTTP address. That is what makes
the three ways of running it the same thing:

| Where | Town process | Model server | Start |
| --- | --- | --- | --- |
| **App** on your own computer | your computer | your computer | `ga town --app` |
| **Server** (workstation, lab machine, a Linux partition on a mainframe) | the server | the same server, or a GPU machine next to it | systemd unit or Docker, below |
| **Site** | any always-on machine | wherever the GPU is | the server setup plus HTTPS and spectators |

## 2. Start it

### As an app

Install [Ollama](https://ollama.com/download) and [uv](https://docs.astral.sh/uv/), then one
command from any folder:

```bash
uvx --from "generative-agents-lab[viewer] @ git+https://github.com/nathanu1/Architecture1@main/feature-social-memory" ga town --app
```

From a checkout it is `ga town --app`. The command checks that the model server answers,
downloads the three models the town uses if they are missing (Llama 3.1 8B, Llama 3.2 3B and an
embedding model, about 7 GB once), founds the town in `runs/town-live/` or continues the one
that is there, and opens it in its own window. Closing the terminal saves the town; the same
command continues it.

| Option | Effect |
| --- | --- |
| `--residents 25` | all 25 residents instead of ten |
| `--app` / `--no-open` | its own window (needs Chrome, Edge, Chromium or Brave) / no window |
| `--model-server URL` or `HEARTHSIDE_LLM_URL` | the model runs on another machine |
| `--parallel N` | model calls sent at once; match the server's parallel slots (§4) |
| `--host 0.0.0.0` | serve other machines; set `HEARTHSIDE_PASSWORD` first |
| `--config FILE`, `--set key=value` | another town config, or single settings |

The page is also installable: in Chrome or Edge use "Install Hearthside" in the address bar, on
a phone "Add to Home Screen". That gives the same live town an icon and a window of its own on
any device that can reach the server.

### On a server

Two equivalent setups. Both continue the same town after any restart.

**systemd** (no containers): [`deploy/hearthside.service`](../deploy/hearthside.service) runs
`ga town` as a service; its header has the five commands to install it. Settings go in
`/etc/hearthside.env`:

```bash
HEARTHSIDE_PASSWORD=choose-one
HEARTHSIDE_SPECTATORS=1
HEARTHSIDE_LLM_URL=http://127.0.0.1:11434
```

**Docker**: `docker-compose.yml` has the town and an Ollama container. Put this in `.env` next
to it, then start both:

```bash
TOWN_MODE=town
TOWN_CONFIG=configs/town_live.yaml
HEARTHSIDE_LLM_URL=http://ollama:11434
HEARTHSIDE_PASSWORD=choose-one
HEARTHSIDE_SPECTATORS=1
```

```bash
docker compose --profile ollama up -d
```

For an NVIDIA GPU, install the NVIDIA Container Toolkit and uncomment the four `deploy:` lines
of the `ollama` service. The compose file sets `OLLAMA_NUM_PARALLEL=4` and keeps the three
models loaded. The image and compose file were written against the documented formats and have
not been built in this repository's CI, so check the first start with `docker compose logs -f`.

**The model server on another machine.** Start Ollama there with `OLLAMA_HOST=0.0.0.0` and
point the town at it with `HEARTHSIDE_LLM_URL=http://that-machine:11434`. Any server that
speaks the OpenAI chat API works the same way (llama.cpp's `llama-server`, vLLM, LM Studio):
use a config with `providers.llm.kind: openai_compatible` and give the address ending in `/v1`.
`providers.llm.pools` names additional servers and `task_overrides.<task>.provider` routes
tasks to them, for example the small model on one machine and the large one on another.

### As a site

Put HTTPS in front of the server and let visitors watch:

```bash
caddy run --config deploy/Caddyfile
```

[`deploy/Caddyfile`](../deploy/Caddyfile) is three lines; Caddy obtains the certificate. With
`HEARTHSIDE_PASSWORD` set and `HEARTHSIDE_SPECTATORS=1`, anyone can open the town and the
inspector, and only someone with the password can talk to residents, build or change the speed.

Without a public address (a machine at home), a tunnel does the same:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

```bash
tailscale funnel 8080
```

## 3. What a day costs

Counted on a recorded ten-resident day (06:00 to 22:00, offline MOCK model, so the counts are
structural; a real model converses and reflects a different amount):

| Setting | Model calls | Change |
| --- | ---: | --- |
| Paper-like engine | 4,592 | 29 per resident per game hour |
| + exact prompt repeats answered from the ledger (`memoize_tasks`) | 2,935 | −36% |
| + recurring situations answered from the ledger (`habit_tasks`) | 2,636 | −43% in total |
| + routine observations not deliberated again (`reaction.salience_gate`) | 2,624 | 17 observations skipped, 9 fewer reaction calls |

A ten-resident day is therefore about **2,600 calls, 1.5 million prompt tokens and 0.1 million
output tokens**; the 25-resident day measured the same way is 7,650 calls and 4.5 million
prompt tokens. Three quarters of the paper-like calls are mechanical (choose a place, rate
importance, ground an action); those are the ones the ledger answers, and the ones that go to
the small model.

What each switch does, and what it gives up:

| Switch | What it does | What it gives up |
| --- | --- | --- |
| `task_overrides` → Llama 3.2 3B | the mechanical tasks use the small model | nothing measurable in the mock; on a real model, coarser place choices |
| `memoize_tasks` | an identical prompt gets the first valid answer recorded for it | sampling variety on exact repeats |
| `habit_tasks` | the same structured situation (same resident, same activity and offered places, same memory text) gets the same answer even when the date or the resident's summary changed the prompt text | the answer no longer reacts to that changed text |
| `reaction.salience_gate` | an observation the resident already decided to carry on past is not sent to the model again for `routine_cooldown_minutes` (60) | a different decision on the second look; each skipped observation is logged as a `reaction_gated` event |
| `retrieval.forgetting` | memories below an activation threshold are skipped before scoring; nothing is deleted | recall of old, never-revisited memories |
| `engine.parallel_calls` | residents think in rounds and a round's calls go out together (§4) | the within-step order of the sequential engine |

Every switch is a row of the run's fidelity table (class X when on) and of the manifest, so a
study can turn exactly one off. The salience gate saved little on the mock day because the mock
rarely answers "carry on"; its effect on a real model is one of the things the first live week
should measure.

## 4. Parallel deciding

A server with a GPU can answer several requests at once. The sequential engine never asks for
more than one. `engine.parallel_calls: N` changes that without giving up replay:

1. Each resident with work left runs, one at a time and in the town's fixed order, until its
   turn ends or reaches a model task.
2. All model tasks reached in that round are sent together, up to N at once.
3. Residents continue with their answers in the same fixed order; the next round begins.

Who runs when depends only on how many model tasks each resident makes, never on how long a
reply took, and a task is a pause point whether the model, a habit or the ledger answers it.
So a replay interleaves exactly as the recorded run did, the town is the same for any N, and a
town stopped mid-step resumes into exactly the uninterrupted one (`tests/test_parallel.py`).
It is a different town from the sequential engine's, because a resident waiting for the model
can be overtaken within the step; that is why it is its own switch.

Measured on the same recorded days (manifest `parallel`):

| Town | Calls made in residents' turns | Waits for the model | Gain |
| --- | ---: | ---: | ---: |
| 10 residents | 2,227 | 945 | 2.4× |
| 25 residents | 6,335 | 2,373 | 2.7× |

Conversations are a turn-by-turn chain and stay sequential (386 and 1,312 calls), so over the
whole day the wait for the model roughly halves. The gain needs a server that really answers
in parallel:

| Server | Setting |
| --- | --- |
| Ollama | `OLLAMA_NUM_PARALLEL=4` (and `OLLAMA_MAX_LOADED_MODELS=3` so both chat models and the embedding model stay loaded) |
| llama.cpp `llama-server` | `--parallel 4` with a context large enough for four slots |
| vLLM | nothing; it batches continuously, so `engine.parallel_calls` of 8 to 16 is reasonable |

Turning the rounds on costs about 0.4 ms of thread hand-off per resident per step, which is
invisible next to a model call and roughly doubles the time of an offline mock run.

## 5. Measure your machine

```bash
ga bench
```

It runs the first 20 game minutes of a three-resident town on your model server (the morning
burst: day plans, schedules, first actions), prints each task's measured latency, sends four
copies of one prompt at once to see whether the server gains from concurrency, and projects how
long a game day takes for 10 and 25 residents with and without parallel deciding. Use
`--model-server URL` for a remote server and `--config` for another town config.

The only real measurement in this repository so far is on four CPU cores with Llama 3.2 3B:
2,525 calls took 4.8 hours of model time, 6.8 seconds per call on average (median 3 s; see the
[town guide](game.md#running-it)). At that rate, one call at a time and with the 3B model for
everything, a ten-resident game day (2,600 calls) is about 5 hours of model time and a
25-resident game day (7,650 calls) about 14 hours: both faster than real time on a machine with
no GPU. The 8B model for the judgment tasks is slower on CPU; `ga bench` tells you by how much
on yours. GPU and Apple Silicon numbers are not measured here; run the bench and trust that.

A town is live at any pace. Residents keep perceiving, planning, talking and remembering; the
clock in the HUD moves as fast as the model allows, and the "thinking" indicator shows who is
waiting.

## 6. Keeping it on

* **It continues, it does not restart.** The town checkpoints every 30 steps (five game
  minutes). `ga town` continues whatever is in its folder; calls recorded after the last
  checkpoint are re-used, never made twice.
* **Move it by copying the folder.** `runs/town-live/` holds the state, the ledger and the
  config. Copy it to another machine and run `ga town --run-dir` there.
* **Watch the disk.** A 25-resident day is about 150 MB of state and ledger. The ledger is the
  habit memory and the replay source, so it stays.
* **Labels stay on.** The HUD names the model and marks mock runs; the inspector shows the
  served model and every call.
* **It is a research run.** The inspector at `/inspector` analyses the live town; every
  experiment metric runs on its snapshots; `ga play --watch runs/town-live` replays it with no
  model calls.
* **One town per process.** Several visitors share one town. For several towns, run several
  services on different ports and folders.

## 7. What is not a path, and why

**Free hosted model APIs.** Checked in November 2026 against the providers' own pages. A
ten-resident day needs about 2,600 requests and 1.6 million tokens, every day:

| Provider | Free allowance | Verdict |
| --- | --- | --- |
| Groq | 1,000 requests and 200,000 tokens per day per model (`openai/gpt-oss-20b`); Llama 3.1 8B and 3.3 70B were shut down on 16 August 2026 ([limits](https://console.groq.com/docs/rate-limits), [deprecations](https://console.groq.com/docs/deprecations)) | an eighth of a day's tokens |
| OpenRouter `:free` models | 50 requests per day, 1,000 after buying 10 credits once ([limits](https://openrouter.ai/docs/api-reference/limits)) | under half a day's requests at best |
| Cerebras | no permanent free tier; $5 of credit for 30 days after adding a payment method ([limits](https://inference-docs.cerebras.ai/support/rate-limits)) | a trial |
| SambaNova | 20 requests per day per model ([limits](https://docs.sambanova.ai/docs/en/models/rate-limits)) | no |
| Cloudflare Workers AI | 10,000 neurons per day; Llama 3.2 3B costs 4,625 per million prompt tokens and 30,475 per million output tokens ([pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)) | one ten-resident day on the 3B model alone uses almost exactly the allowance; nothing left for the 8B |
| Google AI Studio | Flash-Lite models are free of charge with per-project limits shown only in AI Studio, and free-tier content is used to improve Google's products ([pricing](https://ai.google.dev/gemini-api/docs/pricing)) | limits not published; not a Llama |

Free machines do not change this: Oracle's Always Free Arm instance is now 2 cores and 12 GB
and idle instances are reclaimed
([Oracle](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm));
Render's free service sleeps after 15 minutes and has no disk
([Render](https://render.com/docs/free)); Hugging Face Docker Spaces need a paid plan
([Hugging Face](https://huggingface.co/docs/hub/spaces-overview)); Fly.io has no free
allowance ([Fly](https://docs.fly.io/about/pricing)). The allowances also change every few
months. A town meant to stay on for weeks should not depend on them, so free means hardware
you already have: `ga town` on your own machine and a tunnel.

The plumbing for remote APIs still exists and is tested (`providers.llm.kind:
openai_compatible`, `providers.llm.rate_limit` to stay inside a plan's limits,
`configs/town_llama_api.yaml`), because the research path sometimes wants a larger model for
one experiment. It is not a way to keep the town on.

**A static recording.** `ga export-demo` publishes a recorded town as a page with no server.
It is a good companion (always reachable, free to host) but it is a recording: nobody can act
in it and nothing new happens.
