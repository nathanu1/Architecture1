# Testing guide: running Hearthside and the research platform step by step

This guide takes you from an empty machine to running simulations, opening the dashboards,
running experiments and reading their results. Every command is run in a **terminal** on your
own computer:

* **macOS**: open *Terminal* (Applications → Utilities → Terminal) or iTerm.
* **Linux**: any terminal.
* **Windows**: open *PowerShell* or *Windows Terminal*. Where this guide says
  `source .venv/bin/activate`, run `.venv\Scripts\activate` instead. Everything else is the same.

Nothing is hosted anywhere: the simulation runs in your terminal, writes its results to a
`runs/` folder next to the code, and the dashboards are small local web servers you open in
your browser at `http://127.0.0.1:8000` or `:8080`. Close them with `Ctrl+C` in the terminal.

Expected times are for a laptop with four cores. All steps in parts 1–6 need no API key, no
model download and no internet after the install: they use the deterministic offline **MOCK**
model, whose words are mechanical. Part 7 shows the two ways to use a real model.

---

## Part 1: install (about 5 minutes)

**1.1 Prerequisites.** Python 3.11 or newer and `uv`.

```bash
python3 --version
```

Install `uv` if you do not have it (macOS/Linux):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**1.2 Get the code.**

```bash
git clone https://github.com/nathanu1/Architecture1.git hearthside
```

```bash
cd hearthside
```

```bash
git checkout main/feature-social-memory
```

(`feature-determinism/memory-planning-ablation` holds the same work merged through pull
request #1; either branch is fine.)

**1.3 Create the environment and install.**

```bash
uv sync --extra dev --extra viewer
```

```bash
source .venv/bin/activate
```

Your prompt now shows `(hearthside)` or `(.venv)`. Every later command assumes this
environment is active in the terminal you are using; if you open a new terminal, `cd hearthside`
and activate it again.

**1.4 Check the install.**

```bash
ga doctor
```

Expected: a list of lines starting `[ok  ]` or `[WARN]`. Warnings about the "mock fixture",
"no pricing file" and the missing paper PDF are normal. No line should say `[FAIL]`.

```bash
pytest
```

Expected, after about one minute: `217 passed, 1 skipped`.

---

## Part 2: the five-minute tour of the research features (about 1 minute of compute)

```bash
python examples/research_platform.py
```

What it does: runs four residents from 06:00 to 14:00 with the mock model, then prints

* each resident's **relationship records** (familiarity, valence, conversations, encounters),
  the network density and components, and the same network rebuilt from the event log at 10:00;
* **behavior** measures: actions, scheduled share, plan adherence, replans, idle share;
* the **belief ledger**: who has a received memory of the party and who has grounds to believe
  someone else knows;
* a **planted-fact retrieval probe** with and without forgetting;
* a **counterfactual fork**: the same morning re-run from the 12:00 snapshot with a fire in
  Hobbs Cafe at 12:05, and the adaptation measures of the fork versus the original.

The last line names a temporary folder with both runs; you can open either with
`ga serve --run-dir <that folder>/fire`.

---

## Part 3: run a simulation and explore the dashboard (about 3 minutes)

**3.1 Run two simulated days with five residents.**

```bash
ga run --config configs/offline_pilot_2day.yaml --run-id demo --set "social.appraisal=llm"
```

Expected: progress lines every simulated hour, then `status: completed at Wed 15 Feb 2023
00:01:00`, about 5,000 mock calls, in roughly 45 seconds. The run is in `runs/demo/`.

The `--set "social.appraisal=llm"` part turns on the per-conversation appraisal so the
network tab shows valence; leave it out for a paper-exact run.

**3.2 Add the probe-based evaluation** (diffusion, relationships, attendance, failure taxonomy):

```bash
ga evaluate --run-dir runs/demo
```

Expected: lines like `final    valentines_party   claimed 5/5, claimed and supported 5/5`
and a path to `runs/demo/exports/evaluation/report.md`.

**3.3 Open the research viewer.**

```bash
ga serve --run-dir runs/demo
```

Open http://127.0.0.1:8000 in your browser. Leave the terminal running; `Ctrl+C` stops it.

What to try, tab by tab:

| Tab | What to look at |
| --- | --- |
| **Town** | Press play (space) or drag the slider; click a resident on the map; the inspector on the right shows its plan, the memories retrieved for its last decision with recency/importance/relevance bars, the reflection trigger and its conversations. Click a day-timeline lane to jump in time. |
| **Retrieval** | Pick a resident; every retrieval trace lists all candidates with raw and normalized components and explains why #1 outranked #2. |
| **Reflections** | Insights and the evidence tree of memories each one cites. |
| **Decisions** (new) | Pick a resident and a day. Every recorded engine event (day plan, actions, reactions, replans, conversations, reflections) with the retrieval traces and model calls it cites. The "recorded" tag means nothing here is generated after the fact. Click "explain" on a trace to jump to its retrieval. |
| **Network** (new) | The mutual-tie graph; drag the slider to replay the day from the relationship event log; density and reciprocity over time; the selected resident's own records with familiarity bars and valence. |
| **Behavior** (new) | Plan adherence, scheduled share, idle share, replans, reactions and conversations per resident, plus stacked counts per simulated hour. |
| **Beliefs** (new) | Per seeded topic: who holds a received memory, from whom, with which details; the second-order matrix (who has grounds to believe whom knows); the Theory-of-Mind probe table once one has been run (part 5). |
| **Social** | The `ga evaluate` results: claimed versus memory-supported awareness, relationship density, attendance, failure categories. |
| **Interviews** | Appears after `ga interview --run-dir runs/demo --protocol configs/interviews_reference.yaml` (about a minute). |

**3.4 Export everything as files** (optional):

```bash
ga export --run-dir runs/demo
```

Writes `runs/demo/exports/run/` with `events.jsonl`, `transcripts.jsonl`,
`retrieval_traces.jsonl`, `model_calls.jsonl`, `memories.csv`, `plans.csv`,
`relationships.csv`, `relationship_events.jsonl` and a Markdown report.

---

## Part 4: the town game interface (optional, about 1 minute to start)

```bash
ga play --config configs/town_mock.yaml --open
```

Opens http://127.0.0.1:8080: a live three-resident town you can pause, walk around in, chat
with residents and build things in. The research inspector is at
http://127.0.0.1:8080/inspector and has the same Decisions, Network, Behavior and Beliefs
views as the research viewer, drawn in the town's style; open it after a few game hours so the
residents have met. `Ctrl+C` stops it; `ga play --resume runs/<id>` continues a
saved town, `ga play --replay runs/<id>` replays one without model calls.

---

## Part 5: run the three research experiments

Each protocol runs every condition for several seeds, computes the named metrics, and writes
a report. Run them one at a time; each prints a line per run as it completes.

**5.1 Experiment C: adaptation to a fire (fastest, about 1.5 minutes total).**

First record the shared morning with a snapshot at 10:00:

```bash
ga run --config configs/offline_pilot_2day.yaml --run-id adaptation_source --set "output.snapshots=[initial, '2023-02-13T10:00:00', final]" --set scenario.end=2023-02-13T14:00:00
```

Then run the forks (control, fire, fire with the hourly-only planner; three seeds each):

```bash
ga experiment --protocol configs/experiments/adaptation_fork_mock.yaml --execute
```

Read the report:

```bash
cat runs/experiments/adaptation_fork_mock/report.md
```

Or open it in the viewer together with one of the forks:

```bash
ga serve --run-dir runs/experiments/adaptation_fork_mock/fire-s7 --experiment runs/experiments/adaptation_fork_mock
```

In the **Experiment** tab you see the hypothesis, every run, the by-condition table and the
comparisons; in **Decisions** for Isabella at 10:05 you see her reaction to the fire and the
replan it caused; in **Beliefs** the fire does not appear (it is not a seeded topic), which is
expected.

**5.2 Experiment A: memory architecture and consistency (about 10 minutes).**

```bash
ga experiment --protocol configs/experiments/memory_consistency_mock.yaml --execute
```

Twelve two-day runs (full, no reflection, forgetting, recency-only × 3 seeds) plus one
determinism re-run. Report: `runs/experiments/memory_consistency_mock/report.md`. Per-run
details for every metric are in `runs/experiments/memory_consistency_mock/<run>/exports/metrics/`.

**5.3 Experiment B: social network emergence (about 7 minutes).**

```bash
ga experiment --protocol configs/experiments/social_network_mock.yaml --execute
```

Twelve one-day runs of ten residents. Report: `runs/experiments/social_network_mock/report.md`.
Open any run with `ga serve` and use the **Network** slider to watch the ties form.

What I observed when I ran these three with the mock, and how to read them, is in
[`experiments/README.md`](experiments/README.md). Your numbers should match exactly: the mock
is deterministic for a given seed, and the determinism check in experiment A verifies that.

**5.4 Change a protocol.** Copy one of the YAML files, edit `conditions` (any config override),
`metrics` (`evaluation`, `network`, `behavior`, `memory_probe`, `beliefs`, `tom`, `adaptation`),
`seeds` and `primary_outcomes`, then run it the same way. `ga experiment --protocol FILE`
without `--execute` only plans and estimates. The `tom` metric adds the Theory-of-Mind probe
(interview calls on the final snapshot) and fills the Beliefs tab's probe table.

---

## Part 6: counterfactuals, forgetting and planner ablations by hand

Fork the recorded morning from part 5.1 with the hourly-only planner and run it:

```bash
ga fork --run-dir runs/adaptation_source --snapshot 2023-02-13T10-00-00 --out runs/my-fork --set planning.decompose=false --run
```

Fork it with your own intervention: write a file `my_fire.yaml`:

```yaml
interventions:
  - {kind: ambient, at: "2023-02-13T10:30:00", id: fire1, tile: [78, 19], subject: fire, object: burning, description: "a fire is burning in Hobbs Cafe", until: "2023-02-13T11:00:00"}
  - {kind: object_state, at: "2023-02-13T10:30:00", address: "the Ville:Hobbs Cafe:cafe:cooking area", state: burning}
```

```bash
ga fork --run-dir runs/adaptation_source --snapshot 2023-02-13T10-00-00 --out runs/my-fire --interventions my_fire.yaml --run
```

Run a fresh simulation with forgetting on and inspect what was excluded:

```bash
ga run --config configs/offline_smoke.yaml --run-id forgetful --set retrieval.forgetting.enabled=true --set retrieval.forgetting.threshold=-0.6
```

```bash
ga inspect-memory --run-dir runs/forgetful --agent isabella_rodriguez --query "Valentine's Day party" --k 10
```

In the viewer's Retrieval tab, excluded memories are counted per trace with their activation.

Other switches you can pass with `--set` to any `ga run`:

| Setting | Effect |
| --- | --- |
| `architecture.reflection=false` | no reflection |
| `planning.decompose=false` | hourly-only planner |
| `retrieval.weights.importance=0 --set retrieval.weights.relevance=0` | recency-only retrieval |
| `social.appraisal=llm` | appraisal calls after conversations (valence) |
| `social.inform_prompts=true` | the resident's own relationship record goes into its prompts |
| `dialogue.cooldown_minutes=30` | residents may talk again sooner |
| `scenario.population="[isabella_rodriguez, maria_lopez]"` | a smaller cast |

Every default is listed in `configs/defaults.yaml`.

---

## Part 7: using a real model

**7.1 Local model with Ollama (no cost).** Install Ollama from https://ollama.com, start it, then:

```bash
ollama pull llama3.2:3b
```

```bash
ollama pull nomic-embed-text
```

```bash
ga doctor --config configs/town_ollama.yaml
```

Run a short slice of three residents (on four CPU cores each call takes seconds to tens of
seconds, so a morning takes a while; a GPU helps):

```bash
ga run --config configs/ollama_pilot.yaml --set providers.llm.model=llama3.2:3b --set scenario.end=2023-02-13T10:00:00 --set "social.appraisal=llm" --run-id ollama-slice
```

Then `ga serve --run-dir runs/ollama-slice` as before. To run an experiment on Ollama, copy a
protocol and set `base_config: configs/ollama_pilot.yaml`; keep `determinism_check: true` so the
report states whether the model's sampling reproduced itself.

**7.2 Hosted API.** Export your key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`), install the
adapter (`uv sync --extra anthropic` or `--extra openai`), run
`ga doctor --config configs/live_pilot.yaml`, and start with a bounded slice:

```bash
ga run --config configs/live_pilot.yaml --set scenario.end=2023-02-13T09:00:00 --run-id live-slice --yes
```

`--yes` is required because live runs spend money; the budget ceilings in the config stop the
run at the last checkpoint if they are crossed, and `ga resume` continues it. The hosted
adapters follow the current SDKs but were not exercised against the live APIs in the documented
runs, so read the first slice carefully before scaling.

---

## Part 8: if something goes wrong

| Symptom | What to do |
| --- | --- |
| `ga: command not found` | The environment is not active: `source .venv/bin/activate` (Windows: `.venv\Scripts\activate`). |
| `run directory ... already exists` | Pick another `--run-id` or delete the folder under `runs/`. |
| `scenario files changed since this run started` | You edited a scenario while a run existed; start a new run id. |
| The browser shows nothing | Check the terminal running `ga serve`/`ga play` is still up and the address is `127.0.0.1`, not `localhost` behind a proxy. |
| `[FAIL] ollama` in `ga doctor` | Start Ollama (`ollama serve` or the app) and pull the models named in the message. |
| A run stops with `budget_exhausted` or `provider_failure` | Expected safety behavior; `ga resume --run-dir runs/<id>` continues from the last checkpoint and re-uses the calls already recorded. |
| Tests fail after you change a prompt template | Regenerate its example page: `ga prompt-examples --run-dir <a run that used it> --out prompts/examples`. |

Reference material: `docs/reference.md` (every command and config), `docs/research_platform.md`
(the research extensions in depth), `docs/experiments/README.md` (the executed experiments),
`docs/game.md` (the town interface).
