# Plan: two paths, one town

Hearthside is **a living town you can study**. It has exactly two paths, and they share one
engine, one call ledger and one interface:

1. **The living town on a local Llama.** A town that stays on, served by a model you run
   yourself, reachable as an app, from a server, or as a site. Guide: [deploy.md](deploy.md).
2. **The research route.** Controlled runs, forks, metrics and protocols that make claims about
   that town. Guide: [research_platform.md](research_platform.md).

Everything else is in service of these two. This page records why the local path is built the
way it is, what is done, and what comes next, in order.

## Why a local model, served over an API

The town needs about 2,600 model calls and 1.6 million tokens per game day for ten residents
(measured; [deploy.md](deploy.md) §3). Three ways to supply that were weighed:

| Option | Outcome |
| --- | --- |
| Free hosted APIs | The largest free allowance found is an eighth of one day's tokens, the model lists change every few months, and two of the Llama models this project documented were withdrawn in August 2026. Not a base for a town that stays on ([deploy.md](deploy.md) §7 has the sources). |
| Paid hosted APIs | Work, and stay available for a single experiment that wants a larger model. A town that never stops would pay for every hour forever. |
| A model you serve yourself | A fixed cost you may already have paid (a desktop GPU, a Mac, a lab server), no rate limits, a pinned model version that makes weeks-long runs comparable, and prompts that never leave the machine. |

"Local" here means *yours*, not *on the same computer*. The town talks to the model through
one HTTP address, so the model server can be the laptop the town runs on, a GPU machine in the
next room, or a partition of a large shared system. That single seam is the design decision the
rest follows from.

## How one design runs as an app, on a server, and as a site

| Requirement | How it is met |
| --- | --- |
| Runs anywhere | The town process is Python and SQLite with no native code of its own; all model work is behind `HEARTHSIDE_LLM_URL`. Ollama, llama.cpp and vLLM are interchangeable behind it. |
| One command | `ga town` checks the model server, downloads missing models, founds or continues the town and opens it. Configs, prompts, scenarios and the built interface ship inside the package, so it works from any folder through `uvx`. |
| Feels like an app | `ga town --app` opens a window without browser chrome; the page carries a web-app manifest, so it installs from the browser on a desktop or a phone. One interface, no second codebase. |
| Runs on a big server | `deploy/hearthside.service` and `docker-compose.yml`; a restart continues the same town; `engine.parallel_calls` uses a server's parallel slots. |
| Is a site | HTTPS through Caddy or a tunnel; `HEARTHSIDE_SPECTATORS=1` lets anyone watch while a password is needed to act. |
| Cheap enough to leave on | Small model for mechanical tasks, ledger answers for repeats and habits, the salience gate, forgetting. 4,592 calls per ten-resident day became 2,624. |
| Still a research instrument | Every switch is a fidelity-table row; the town is deterministic for any parallel setting, replays exactly, and resumes into the same town it would have been. |

The human-brain analogy that guided the cost work, stated plainly: most of what a resident does
all day is routine, and routine does not need deliberation. Habits answer the situations
already settled, attention skips what was already judged unremarkable, a small fast model
handles mechanical judgments and a larger one is kept for plans, reflection and conversation,
forgetting keeps recall bounded, and residents think at the same time rather than in a queue.
Each is a switch because each changes when the mind is consulted, and that is a research
question in its own right.

## Done

| Piece | Evidence |
| --- | --- |
| Habit cache, salience gate, memoized repeats | `tests/test_cheap_town.py`, `tests/test_live_town.py`; measurements in [deploy.md](deploy.md) §3 |
| Parallel deciding, deterministic and replayable | `tests/test_parallel.py`; gains in [deploy.md](deploy.md) §4 |
| Model servers by name, each with its own model and limits | `providers.llm.pools`, `tests/test_cheap_town.py` |
| `ga town`, `ga bench`, model download, remote model server | `tests/test_town.py` |
| Package runs from any folder | wheel built and run from an unrelated directory |
| Installable page, app window | manifest and icons in the built interface; checked in a browser |
| Server units | `deploy/hearthside.service`, `docker-compose.yml`, `deploy/entrypoint.sh` |

Not yet verified, and said so where it matters: no real model has been run on this work (the
development sandbox could not install one), so every latency in the docs that is not the
documented four-core run is something `ga bench` has to measure on your machine; and the Docker
image has not been built in CI.

## Next, in order

1. **One town on, for a week.** `ga bench`, then `ga town` on the machine that will host it,
   spectators on, a tunnel or Caddy in front. Keep a log: where it stalls, what residents say
   by day five, what breaks on restart, real calls per day against the mock's 2,600. Nothing
   else until it has run a week.
2. **Measure the switches on a real model.** The same recorded day with each switch off in
   turn (`ga fork` from one snapshot keeps the past identical): calls saved, and plan
   adherence, reaction mix and memory-probe recall from the existing metrics. This is the
   small result "how little deliberation does a believable resident need?".
3. **One research question, properly.** Experiment B on the real model: does a stable social
   structure form from local encounters, and does telling residents about their own
   relationships change who they talk to? Three seeds, the determinism check, written up like
   the mock write-ups.
4. **Only then widen.** Parallel conversations (the remaining sequential half of the model
   time), 25 residents as the default, a public page, and the proposals in
   [research_review.md](research_review.md).

## What was dropped

* Free hosted APIs as a way to keep the town on (reasons above). The adapter and a client-side
  rate limiter remain for single experiments.
* A separate desktop or mobile codebase. The installable page and `--app` cover it.
* A static recording as the public face. It stays as a companion (`ga export-demo`), not a path.
