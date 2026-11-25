# The research platform

Hearthside's research extensions turn the *Generative Agents* reproduction into a platform
for systematic experiments on agent cognition and social dynamics. This guide explains the
architecture, the configuration, the measures, the experiment runner, the dashboard, and the
rules that keep every result auditable. The literature behind each piece is in
[`research_review.md`](research_review.md); the state of the system before this work is in
[`system_assessment.md`](system_assessment.md); the executed demonstration experiments are in
[`experiments/`](experiments/README.md).

Every extension is **off by default or purely observational**, so a default run still follows
the paper's architecture exactly (the reproduction spec's fidelity table lists each new
setting, class X when switched on). Nothing added here is ever rendered into an agent's
prompt unless a setting says so explicitly.

## 1. Architecture

```
scenario ──► engine (snapshot · decide · commit) ──► state.sqlite ─┬─► viewer (read-only)
                │                                                   ├─► metrics (run level)
    cognition ──┤  memory ── retrieval (+ forgetting filter)        ├─► belief ledger
                │  planning (+ hourly-only ablation)                └─► experiment reports
                │  reaction · dialogue (+ social line, opt-in)
                └─ social memory ── relationships + relationship_events
```

| Module | Role | Writes | Model calls |
| --- | --- | --- | --- |
| `memory/retrieval.py` `Forgetting` | Activation-based accessibility filter before scoring | retrieval traces (`excluded` entries) | none |
| `cognition/planning.py` (`planning.decompose`) | Hour blocks as single tasks when off | plans | fewer |
| `social/relationships.py` | Directed relationship records with interpretable updates | `relationships`, `relationship_events` | none |
| `social/service.py` | Engine hooks: after conversations, on co-presence; optional appraisal call; prompt line | events (`appraisal_failure`) | one per participant per conversation when `social.appraisal: llm` |
| `social/network.py` | Density, degree, reciprocity, clustering, components; reconstruction at any time | none | none |
| `cognition/beliefs.py` | Per-agent, per-topic exposures with provenance and detail values; second-order grounds | none | none |
| `evaluation/tom.py` | "Does B know about X?" interview probe scored against grounds and truth | `exports/tom/` | interviews on a clone |
| `evaluation/behavior.py` | Plan adherence, scheduled share, idle share, replans, reactions; adaptation after an intervention | none | none |
| `evaluation/memory_probe.py` | Planted-fact recall@k and own-experience recall on a snapshot clone | none | none (embeddings only) |
| `evaluation/metrics.py` | Registry of run-level metrics for protocols | `exports/metrics/*.json` | depends on metric |
| `simulation/fork.py`, `ga fork` | Counterfactual runs from a snapshot | a new run directory | as a run |
| `evaluation/experiment.py` | Protocols with named metrics, forks, interventions, determinism check | `runs/experiments/<name>/` | as runs |
| `viewer/` | Decisions, Network, Behavior, Beliefs tabs; generic experiment comparison | none | none |

### Information scope

The engine's rule that an agent's prompt is rendered only from its own identity, memories
and perceptions is unchanged. The social memory is the agent's *own* record of its
interactions (it is written only by events the agent took part in or perceived), so showing
it to the agent (`social.inform_prompts`) adds no information the agent could not have.
The belief ledger, the truth it is compared with, every metric and every dashboard view are
evaluator-side and never reach a prompt; `tests/test_beliefs_tom.py` checks that probe
prompts carry neither grounds nor truth.

## 2. Configuration

All settings live in the run config (`configs/defaults.yaml` lists every default).

```yaml
retrieval:
  forgetting:                 # research extension, off by default
    enabled: false
    decay: 0.5                # ACT-R d
    threshold: -1.0           # activation below this = inaccessible
    importance_bonus: 0.1     # per importance point above one
planning:
  decompose: true             # false = hourly-only planner (no 5-15 min tasks, no replan calls)
social:
  track: true                 # keep relationship records (no calls, no prompt change)
  appraisal: none             # llm = one appraisal call per participant per conversation
  inform_prompts: false       # render the agent's own record into reaction/dialogue prompts
  familiarity_gain_conversation: 0.25
  familiarity_gain_presence: 0.03
  presence_cooldown_minutes: 60
  valence_rate: 0.3           # EMA rate for appraisals (scaled -1..1)
  decay_per_day: 0.02         # familiarity lost per day without contact
  tie_threshold: 0.2          # familiarity needed for a network tie
```

**Forgetting.** A memory's base-level activation is `ln(t_c^-d + t_a^-d) + bonus·(importance-1)`
with `t_c`, `t_a` the hours since creation and since last retrieval, offset by one. With the
defaults a memory made now scores ln 2 ≈ 0.69; an unretrieved day-old memory of importance 3
scores about −0.72 and importance 8 about −0.22. Sub-threshold memories are excluded before
scoring and listed in the retrieval trace with their activation; the stream is never
altered. Retrieval refreshes `t_a`, so often-used memories stay accessible (the spacing effect
of Anderson & Schooler 1991).

**Social memory.** For each directed pair the record holds familiarity in [0, 1], valence in
[−1, 1], counts, and timestamps. A conversation applies `f += g·(1−f)`; co-presence in the
same arena applies the smaller gain at most once per cooldown; familiarity decays lazily by
`(1−decay)^days` since the last update. With `appraisal: llm`, each participant is asked
once how the conversation left it feeling about the other (−2..2; `prompts/conversation_appraisal.v1.md`)
and valence moves toward that rating by `valence_rate`. A failed appraisal leaves valence
unchanged and logs `appraisal_failure`. Every update appends to `relationship_events` with
the values before and after.

**Hourly-only planner.** With `planning.decompose: false` each hour block is followed as one
task and an interruption resumes the block without a replan call. Day and hour planning are
unchanged.

## 3. Measures

### Retrieval probes (`evaluation/memory_probe.py`)

Run on an in-memory clone of a snapshot, so the run is never touched. *Planted facts*
(`configs/probes/memory_facts.yaml`, or the second set `memory_facts_v2.yaml`) are inserted
for every agent at chosen ages and importance levels and queried; the report gives recall@k,
recall@30, a recall curve (k = 1 … 100), the median rank and mean rank percentile, mean
reciprocal rank, recall by age and by importance, and how many facts the forgetting filter
excluded. *Own experiences* queries each conversation's summary and checks whether a memory
of that conversation is delivered. With the hash-embedding fixture relevance is lexical;
the report names the embedding model.

Three options were added after the first experiments (see
[`experiments/round2.md`](experiments/round2.md)):

* **Query styles.** A fact may carry `queries: {lexical: ..., paraphrase: ...}`. The lexical
  query shares content words with the statement; the paraphrase shares none (a test checks
  this). Their gap separates word matching from semantic retrieval.
* **Scoring variants.** `metric_params.memory_probe.variants` maps a name to overrides of the
  run's retrieval settings (`{"weights.recency": 0}`, `{"forgetting.enabled": true, ...}`).
  The same planted facts in the same snapshot are re-scored under each variant, so a
  variant comparison is exact: nothing but the scoring differs. Outcomes are named
  `memory_recall_at_30__<variant>` and so on.
* **Anchors.** A fact with `anchor: true` is planted and never queried; it changes the
  stream, for example its age range (`examples/round2_horizon.py`).

### Behavior (`evaluation/behavior.py`)

From plans, events and frames: scheduled share of actions, plan adherence (hour blocks with
at least one scheduled action started), superseded tasks, replans, reaction decisions by
kind, idle share, conversations, failures and refusals; per agent, pooled, and per hour.
`adaptation(db, agents, at, keywords, window)` reports, after an intervention, who perceived
it (from reaction observations), who reacted or replanned, the latency of the first change,
and conversations mentioning it.

### Social network (`social/network.py`)

Ties are familiarity ≥ `tie_threshold`; the undirected network keeps mutual ties (the paper's
convention for relationship density). Density `2|E|/(n(n−1))`, mean degree, degree
distribution, reciprocity, average local clustering, components, mean familiarity and
valence. `reconstruct(db, at)` replays `relationship_events`, so a time series needs no extra
bookkeeping.

One conversation already lifts familiarity above the default threshold of 0.2, so the
thresholded density saturates quickly. Three additions avoid resting a conclusion on that
one number: `threshold_sweep` (the thresholded measures at 0.2, 0.35, 0.5 and 0.75, or the
values in `metric_params.network.thresholds`), `weighted_density` (the mean over all pairs
of the weaker direction's familiarity; no threshold) and `conversation_density` (the share
of pairs who talked). Reciprocity is close to 1 by construction, because a conversation
updates both records by the same rule; it is reported, not interpreted.

### Beliefs and Theory of Mind (`cognition/beliefs.py`, `evaluation/tom.py`)

For each evaluator topic and agent: exposures (seed, statement heard, inner voice, direct
observation) with time, source and the detail values stated (date, time, place, ...);
*variants* when sources gave different surface values; and *grounds* about every other agent
(A told B, or A heard B mention it). Truth is whether B's own memory holds a supported
exposure. The ToM probe asks A "Does B know about <topic>?" on a snapshot clone, labels the
answer with the awareness classifier and scores it:

| A claims B knows | A has grounds | B knows | label |
| --- | --- | --- | --- |
| yes | yes | yes | grounded_correct |
| yes | no | yes | ungrounded_correct |
| yes | any | no | over_attribution |
| no | yes | yes | under_attribution |
| no | no | yes | unaware_of_other |
| no | any | no | correct_negative |

Summary: attribution precision, attribution recall, grounded share of claims, and
knowledge coverage (pairs where A has grounds about B, of pairs where B knows).

## 4. Experiments

A protocol is a YAML file (`configs/experiments/*.yaml`):

```yaml
name: adaptation_fork_mock
base_config: configs/offline_pilot_2day.yaml
fork_from: {run_dir: runs/adaptation_source, snapshot: "2023-02-13T10-00-00"}   # optional
question: "..."
hypothesis: "..."                       # fixed before running; printed in the report
conditions:
  control: []
  fire: []
  fire_hourly: ["planning.decompose=false"]
interventions:                          # optional, per condition
  fire: [{kind: ambient, at: "2023-02-13T10:05:00", id: cafe_fire, tile: [78, 19], subject: fire, object: burning, description: "a fire is burning in Hobbs Cafe", until: "2023-02-13T11:00:00"}]
seeds: [7, 8, 9]
metrics: [adaptation, behavior, beliefs]   # names from evaluation/metrics.py; usage is always added
metric_params:
  adaptation: {at: "2023-02-13T10:05:00", keywords: [fire, burning, smoke], window_minutes: 120}
primary_outcomes: [adaptation_changed_share, adaptation_median_latency_min]
determinism_check: true                # re-run the first configuration and compare state hashes
output_dir: runs/experiments
```

`ga experiment --protocol FILE` plans and estimates; `--execute` runs every condition × seed,
computes the metrics, writes `runs.csv`, `rows.json`, `summary.json`, `report.md`,
`protocol.json` and one strip chart per primary outcome. Every number in the tables can be
traced to `<run>/exports/metrics/<metric>.json`.

**Statistics.** Every pair of conditions is compared on every primary outcome (omitted above
six conditions), two ways:

* *unpaired*: mean difference, bootstrap interval, and a permutation test over run labels
  (exact up to 16 pooled runs, Monte Carlo beyond);
* *paired by seed*: the conditions of a protocol run on the same seeds, so the report also
  gives the mean within-seed difference, how many seeds moved in its direction, the effect
  size d_z, and an exact sign-flip permutation test.

Each test is printed with the smallest p-value its design can produce (0.1 for three runs a
side; 2/2ⁿ for n paired seeds), so a p-value at the floor is recognizable as such. When
neither condition varies between seeds, the report says that the seeds are copies and the
p-value describes determinism.

**Planned contrasts.** A protocol can register the comparisons its hypothesis is about:

```yaml
contrasts:
  - {label: "H1 paraphrase recall: semantic > hash", outcome: memory_recall_paraphrase_at_30, a: full, b: hash_embeddings, expect: ">"}
  - {label: "H4 no reflection = full", outcome: memory_recall_at_30, a: no_reflection, b: full, expect: "=", tolerance: 0.05}
  - {outcome: memory_recall_old_at_30__no_recency, outcome_b: memory_recall_old_at_30, a: full, b: full, expect: ">"}
```

`expect` is `>`, `<`, `>=`, `<=` or `=` (with `tolerance`); `outcome_b` compares two outcomes
of the same runs, for example a probe variant against the paper weights. The report lists
each contrast with its direction verdict, the number of seeds agreeing, d_z, the paired p and
the Holm-adjusted p **within the planned family only**. All other pairwise comparisons stay
in the report as exploration.

**Parallel runs and re-analysis.** `--jobs N` runs N simulations at a time in worker
processes; rows keep the protocol's order. `GA_SQLITE_SYNCHRONOUS=OFF` skips the disk sync
of every commit, which made 25-resident mock runs about 40% faster with bit-identical
results; a crash can then corrupt the run being written, so use it for batches you can
re-run. `ga experiment --protocol FILE --rebuild` re-analyses an executed experiment from
`rows.json` without running anything.

**Report detail.** Below the run-level tables the report pools the per-run metric files by
condition (`evaluation/detail.py`): planted-fact recall by age, importance and query style
with the recall curve and the scoring variants; network density at every threshold, the
clustering-to-density ratio and density over time; and who perceived an intervention.

**Forks.** `ga fork --run-dir R --snapshot NAME --out DIR [--set k=v] [--interventions FILE] [--run]`
creates a run that continues from a committed snapshot of another run with a fresh ledger;
`fork_from` in a protocol does the same for every run. A fork that changes nothing reproduces
the source's own continuation with the mock model (tested), which is the baseline every
counterfactual is compared against.

With the mock, a fork's seed changes nothing after the fork point, so forks of one source
are copies, not replicates. `fork_from.run_dir` may therefore contain `{seed}`: each seed
then forks from its own recorded past, and `fork_from.create` names the config and overrides
that produce a missing source:

```yaml
fork_from:
  run_dir: "runs/experiments/adaptation_fork_v2_sources/s{seed}"
  snapshot: "2023-02-13T12-30-00"
  create: {config: configs/research_n25_2day.yaml, overrides: ["output.snapshots=[initial, '2023-02-13T12:30:00', final]", "scenario.end=2023-02-13T12:30:10"]}
```

With a sampled model the opposite design is informative as well: one shared past and
several seeds show how much the future varies from the model's sampling alone
(`configs/experiments/fire_llama32.yaml`).

**Interventions** are the engine's existing kinds: `object_state`, `ambient`, `end_ambient`,
`inner_voice`. Agents perceive them like anything else; nothing scripts their reaction.

## 5. Randomness and reproducibility

The manifest of every run now carries a `randomness` section:

* the engine is deterministic given the recorded model responses (fixed agent order,
  snapshot–decide–commit steps);
* the **mock** derives every output from (seed, task, rendered prompt), so two runs with the
  same seed and configuration are identical (the determinism check confirms it);
* **Ollama / OpenAI / OpenAI-compatible** servers receive `seed` where supported; this does not
  make sampling bit-reproducible across servers, versions or batch conditions (He 2025;
  Atil et al. 2024). The seed sent is the run seed plus the request's *occurrence* (how often
  this exact request was already issued in the run): with one fixed seed a server repeats
  its answer to a repeated request, so a plan that failed validation failed identically at
  every later retry (observed with Llama 3.2 3B, `experiments/round2.md` §6). The occurrence
  is part of the ledger key, so the run stays reproducible and replays unchanged;
* the **Anthropic** API accepts no seed, so matched seeds match the initial world only;
* embeddings are a deterministic hash fixture or model embeddings cached by text and model;
* `ga replay` re-executes any run from its ledger and checks the state hash.

Prompt templates are hashed into every request; a changed template therefore breaks replay by
design and is listed in the manifest. Experiment reports print the determinism result next to
every comparison.

## 6. Dashboard

`ga serve --run-dir DIR [--experiment DIR]` adds four tabs to the viewer:

* **Decisions**: per agent and day, every recorded engine event (day plan, action, reaction,
  replan, conversation, reflection, failures, interventions) joined with the retrieval traces
  and model calls it cites, plus the calls the agent made at the same simulated time. Each
  record is labeled *recorded*; no explanation is generated after the fact.
* **Network**: the mutual-tie graph at any time (slider replays the event log), the measures,
  density and reciprocity over time, and the selected agent's own records with familiarity
  bars and valence.
* **Behavior**: pooled and per-agent plan adherence, scheduled share, idle share, replans,
  reactions, conversations, failures, and stacked counts per hour.
* **Beliefs**: per topic, who has a received memory and from whom, conflicting detail values,
  the second-order grounds matrix, and the Theory-of-Mind probe table when one was run.
* **Experiment** now lists the protocol's hypothesis, every outcome by condition, the
  comparisons and the determinism result.

## 7. Command summary

```bash
ga run --config configs/offline_pilot_2day.yaml --run-id base --set "output.snapshots=[initial, '2023-02-13T10:00:00', final]"
ga fork --run-dir runs/base --snapshot 2023-02-13T10-00-00 --out runs/base-fire --interventions my_fire.yaml --run
ga experiment --protocol configs/experiments/memory_consistency_mock.yaml --execute
GA_SQLITE_SYNCHRONOUS=OFF ga experiment --protocol configs/experiments/memory_retrieval_v2.yaml --execute --jobs 3
ga experiment --protocol configs/experiments/memory_retrieval_v2.yaml --rebuild   # re-analyse saved rows
python examples/round2_horizon.py runs/experiments/memory_retrieval_v2 --condition full
ga serve --run-dir runs/experiments/memory_consistency_mock/full-s101 --experiment runs/experiments/memory_consistency_mock
ga export --run-dir runs/base          # adds relationships.csv and relationship_events.jsonl
```

Programmatic use:

```python
from generative_agents.evaluation.metrics import MetricContext, run_metrics
ctx = MetricContext(run_dir, cfg, manifest)
values, failures = run_metrics(ctx, ["network", "behavior", "beliefs"])
```

## 8. Using the platform for a study

1. Write the question and hypothesis into the protocol before running anything.
2. Pick metrics whose inputs are records (network, behavior, beliefs, memory_probe) where
   possible; add probe-based metrics (evaluation, tom) knowing they cost calls and depend on
   the classifier.
3. Run with the mock first: it checks that conditions are wired and measures move in the
   expected direction (it says nothing about agents).
4. Run with a local or hosted model, keep `determinism_check: true`, and report the result.
5. Report run-level means with intervals; treat p-values as descriptive; keep failed runs in
   the table.
6. Do not describe plausibility as validity. Compare against human reference data where it
   exists (the paper's §7 numbers are references, not targets).

## 9. Limitations

* The mock model is a fixture: its words and choices are mechanical, so mock experiments
  validate the pipeline, not agent behavior.
* The awareness classifier labels probe answers; the paper labeled by hand. Labels keep the
  answer text for review.
* Detail *variants* use surface strings, so paraphrases of the same fact count as distinct
  values; they are candidates for review, not errors.
* Social memory updates are rules with chosen constants; they are interpretable, not
  calibrated against human relationship data.
* Forgetting uses two traces (creation, last access) rather than the full access history.
* The engine is synchronous; wall time with real models is model latency.
* The recency term of the paper's score is min-max normalized over an agent's stream, so it
  depends on the oldest memory present: probe results about "old" facts hold for the run
  length they were measured on (see the horizon analysis in `experiments/round2.md`).
* Exact permutation tests on a handful of seeds have a floor (2/2ⁿ paired); with many
  comparisons only planned contrasts can survive a multiplicity adjustment.
