# Demonstration experiments (executed with the offline MOCK model)

Three experiments exercise the research platform end to end. **They were run with the
deterministic mock model and hash embeddings**, so their numbers show that the conditions are
wired, that the measures move in the direction the mechanisms imply, and that the reports and
dashboards work. They are not findings about generative agents, let alone about people. The
same protocols run unchanged with a local or hosted model (`ga experiment --protocol ...
--execute`, see [`../research_platform.md`](../research_platform.md) §4).

Each experiment's full report, run table, per-run metric details and figures are under
`runs/experiments/<name>/` after execution (git-ignored); the condensed results below were
copied from those reports on 2026-11-09. Hardware: a four-core cloud container; wall times
are per run.

Common procedure: `ga experiment --protocol <file> --execute`. Every run is an independent
simulation (or fork) with its own ledger; metrics are computed from the run's records and, for
`evaluation`, from probes on snapshot clones. Seeds are matched across conditions. The mock
derives every output from (seed, task, rendered prompt), so a determinism check (same
configuration twice) is expected to pass; with a sampled model it would not, and the report
would say so.

---

## Experiment A: memory architecture and behavioral consistency

Protocol: [`configs/experiments/memory_consistency_mock.yaml`](../../configs/experiments/memory_consistency_mock.yaml).

**Research question.** How do reflection, retrieval weighting and controlled forgetting change
what agents can recall, how closely they follow their plans, and whether seeded information
still spreads?

**Hypothesis (fixed before running).** Forgetting lowers recall of day-old planted facts
without touching recent ones; recency-only retrieval lowers recall of important old facts;
removing reflection leaves retrieval accuracy unchanged. Plan adherence is expected to be
unaffected by any memory condition with the mock model.

**Conditions** (five pilot agents, 13–15 February, two simulated days):

| Condition | Overrides |
| --- | --- |
| `full` | none (paper defaults) |
| `no_reflection` | `architecture.reflection=false` |
| `forgetting` | `retrieval.forgetting.enabled=true`, `retrieval.forgetting.threshold=-0.6` |
| `recency_only` | `retrieval.weights.importance=0`, `retrieval.weights.relevance=0` |

**Controlled variables.** Scenario, population, seeds (101, 102, 103), prompts, every other
setting, the planted-fact set (`configs/probes/memory_facts.yaml`), k = 10.

**Metrics.** `memory_probe` (planted-fact recall@10, MRR, recall by age; own-conversation
recall), `behavior` (plan adherence, scheduled share, replans, idle share), `evaluation`
(supported party and candidacy recall, attendance), `beliefs`, `usage`. Primary outcomes:
planted-fact recall@k, recall of facts older than a day, own-experience recall, supported party
recall, plan adherence.

**Procedure.** 4 conditions × 3 seeds = 12 runs plus one determinism re-run of `full-s101`.

**Observed results.** See §A results below (filled from the executed report).

**Limitations.** Mock dialogue and reflections are mechanical; hash embeddings make relevance
lexical, so paraphrase recall depends on shared words; three seeds per condition are
exploratory; the party probes depend on the awareness classifier.

---

## Experiment B: social network emergence

Protocol: [`configs/experiments/social_network_mock.yaml`](../../configs/experiments/social_network_mock.yaml).

**Research question.** Do social structures (ties, components, reciprocity) emerge from local
encounters, and how do interaction opportunities change them?

**Hypothesis.** Network density and the largest component rise with contact opportunity
(shorter dialogue cooldown) and fall with less; the probe-based density (mutual claims
validated against memory) tracks the record-based density; informing prompts changes nothing
with the mock model, which does not read the relationship line.

**Conditions** (ten Smallville residents, one day 06:00–22:00, `configs/offline_social_day.yaml`):

| Condition | Overrides |
| --- | --- |
| `baseline` | none |
| `informed` | `social.appraisal=llm`, `social.inform_prompts=true` |
| `low_contact` | `dialogue.cooldown_minutes=720` |
| `high_contact` | `dialogue.cooldown_minutes=30` |

**Controlled variables.** Population, map, seeds (11, 12, 13), prompts, tie threshold 0.2,
all other settings.

**Metrics.** `network` (density, edges, components, reciprocity, clustering, mean familiarity
and valence), `behavior`, `evaluation` with relationship probes (`probe_density_supported`),
`usage`. Primary: network density, largest component, conversations per agent, probe density.

**Procedure.** 4 × 3 = 12 runs.

**Observed results.** See §B results below.

**Limitations.** Mock agents start conversations by a fixed-probability rule that rises when
the observer has a memory naming the other; encounters depend on the mock's location rules;
one day is short for decay to matter.

---

## Experiment C: adaptation to an environmental change (counterfactual forks)

Protocol: [`configs/experiments/adaptation_fork_mock.yaml`](../../configs/experiments/adaptation_fork_mock.yaml).

**Research question.** When a fire breaks out in Hobbs Cafe, how many agents who perceive it
change their plans, how fast, and does word of it reach others? Does an hourly-only planner
adapt differently from the full hierarchy?

**Hypothesis.** Agents in the cafe react within minutes; the share of agents who change plans is
higher in `fire` than in `control` (zero by construction); the hourly-only planner reacts as
often but regenerates fewer tasks.

**Design.** One recorded morning (`runs/adaptation_source`: pilot five, 00:00–14:00, snapshot at
10:00). Every run forks from the 10:00 snapshot, so all conditions share the same past.

| Condition | Overrides | Interventions after the fork |
| --- | --- | --- |
| `control` | none | none |
| `fire` | none | ambient fire at the cafe (10:05–11:00) and the cooking area set to `burning` |
| `fire_hourly` | `planning.decompose=false` | same as `fire` |

**Controlled variables.** Identical state at 10:00 (memories, plans, positions, relationships),
seeds (7, 8, 9), prompts.

**Metrics.** `adaptation` (perceivers, share who changed plans, median latency, mentions in
conversation; keywords fire/burning/smoke, window 120 min), `behavior`, `beliefs`, `usage`.
Primary: changed share, median latency, mentions, replans per agent.

**Procedure.** 3 × 3 = 9 forks of 4 simulated hours each.

**Observed results.** See §C results below.

**Limitations.** The mock reacts to "burning" by rule, so the reaction itself is not a finding;
whether the fire spreads by word of mouth depends on the mock's news rule, which only shares
high-importance seeds and statements; four hours is a short window.
