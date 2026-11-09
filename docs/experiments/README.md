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

**Observed results** (12 runs completed, about 42 s each; determinism check identical;
full table in `runs/experiments/memory_consistency_mock/report.md`):

| Outcome (mean ± SD over 3 seeds) | full | no_reflection | forgetting | recency_only |
| --- | --- | --- | --- | --- |
| Planted-fact recall@10 | 0.375 ± 0 | 0.375 ± 0.025 | 0.375 ± 0 | 0 ± 0 |
| … facts under an hour old | 1.0 | 0.97 | 1.0 | 0 |
| … facts older than a day | 0 | 0 | 0 | 0 |
| Facts excluded by forgetting (of 40) | 0 | 0 | 10 | 0 |
| Own-conversation recall@10 | 0.82 ± 0.10 | 0.81 ± 0.11 | 0.80 ± 0.09 | 0 ± 0 |
| Party recall (claimed and memory-supported) | 0.93 ± 0.12 | 0.93 ± 0.12 | 0.93 ± 0.12 | 0.13 ± 0.12 |
| Plan adherence | 1.0 | 1.0 | 1.0 | 1.0 |
| Conversations per agent | 12.5 | 12.4 | 12.7 | 11.9 |
| Model calls per run | 4,966 | 4,377 | 4,989 | 4,903 |

Reading, with the hypothesis as the yardstick:

* *Recency-only retrieval* collapsed every memory measure: planted facts, the agents' own
  conversations and the seeded party were no longer retrieved (full − recency_only = 0.82
  for own-conversation recall, exact permutation p = 0.1 with n = 3 + 3, the smallest p this
  design can produce). Because the score then depends only on last access, retrieval returns
  whatever was retrieved most recently, a self-reinforcing loop that the three-factor score
  prevents. This part of the hypothesis held.
* *Forgetting* excluded exactly the ten low-importance day-old facts it should (two per agent,
  activation below −0.6) and nothing else, but recall of day-old facts was already **zero in
  every condition**, so the hypothesized drop could not be observed: in a two-day stream of
  about 340 memories per agent, with lexical hash embeddings and k = 10, day-old facts rank
  between 18th and 56th even under the full score (their recency component is low and the
  lexical relevance of a paraphrase is weak). The probe therefore has a floor effect at this k
  for old facts; k = 30 (the paper's retrieval cap) or model embeddings would be needed to
  test the forgetting hypothesis properly. The mechanism itself is verified by the exclusion
  count and by the unit tests.
* *Post-hoc check (added after the runs, not part of the registered outcomes):* recomputing
  recall at the paper's retrieval cap of 30 from the saved rankings gives recall@30 of 0.51
  (full), 0.56 (no_reflection), 0.56 (forgetting) and 0.31 (recency_only), and recall of
  day-old facts at 30 of 0.10, 0.18, 0.17 and 0.0. Under forgetting the two unimportant old
  facts per agent are inaccessible, yet the *important* old facts rank higher because the
  eligible pool is smaller, so old-fact recall is not lower than in `full`. This is the
  mechanism's intended trade-off, observed here with the mock's lexical embeddings; the
  probe now reports recall@30 alongside recall@k for future runs.
* *No reflection* left retrieval accuracy and diffusion unchanged, as hypothesized, and saved
  about 12% of calls.
* *Plan adherence* was 1.0 everywhere with the mock, as expected; with a sampled model this
  measure is where memory conditions could show behavioral consequences.

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

**Observed results** (12 runs completed, 28–39 s each; full table in
`runs/experiments/social_network_mock/report.md`):

| Outcome (mean ± SD over 3 seeds) | baseline | informed | low_contact | high_contact |
| --- | --- | --- | --- | --- |
| Conversations per agent | 7.1 ± 0.6 | 7.5 ± 0.1 | 4.1 ± 0.1 | 10.5 ± 0.3 |
| Network density, mutual ties at familiarity ≥ 0.2 | 0.39 ± 0.01 | 0.39 ± 0.01 | 0.40 ± 0 | 0.39 ± 0.03 |
| Largest component / components | 10 / 1 | 10 / 1 | 10 / 1 | 10 / 1 |
| Mean familiarity over records | 0.46 ± 0.04 | 0.48 ± 0.02 | 0.36 ± 0.01 | 0.55 ± 0.02 |
| Mean valence (appraised conversations only) | n/a | +0.33 ± 0.07 | n/a | n/a |
| Probe density (mutual, memory-supported "know of") | 0.36 ± 0.07 | 0.39 ± 0.06 | 0.32 ± 0.05 | 0.42 ± 0.04 |
| Clustering | 0.53 | 0.56 | 0.57 | 0.57 |
| Model calls per run | 4,811 | 5,097 | 4,234 | 5,547 |

Reading:

* **A connected structure emerged from local encounters in every run**: ten residents who
  started with no records ended the day in one component with about 18 mutual ties (density
  0.39), reciprocity 1.0 and clustering about 0.55. Ties formed through co-presence in the
  cafe, the dorm and the street and through conversations the mock started by its
  "knows the other" rule; nothing scripted them.
* **Contact opportunity moved interaction intensity, not the set of partners.** The dialogue
  cooldown changed conversations per agent from 4.1 (low) to 10.5 (high) and mean familiarity
  from 0.36 to 0.55, and the probe-based density (agents who mutually claim to know each other
  with a memory to support it) rose with it (0.32 → 0.42). The record-based density at the
  0.2 threshold did **not** move, because one conversation or a few encounters already cross
  that threshold and the same people meet in a day regardless of how often they may talk. The
  hypothesis about density therefore held for the probe measure and for familiarity but not for
  the thresholded tie count; a post-hoc recomputation at threshold 0.5 (not a registered
  outcome) gives densities of 0.05 (low), 0.18 (baseline), 0.22 (informed) and 0.22 (high),
  which is the pattern the hypothesis expected. The tie threshold is a reporting choice that
  the protocol should fix in advance and the dashboard lets one vary.
* **Informing prompts changed nothing but valence**, as predicted for the mock, which does not
  read the relationship line: conversations and ties matched the baseline, and the appraisal
  calls produced a mean valence of +0.33 (the mock rates thanks and invitations positively).
  With a real model this is the condition that tests whether social memory feeds back into
  who talks to whom.

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

**Observed results** (9 forks completed, 5–7 s each; full table in
`runs/experiments/adaptation_fork_mock/report.md`):

| Outcome (mean over 3 seeds) | control | fire | fire_hourly |
| --- | --- | --- | --- |
| Agents who perceived the fire | 0 | 1 (Isabella, in the cafe) | 1 |
| Share of agents who changed plans | 0 | 0.2 | 0.2 |
| Changed plans among perceivers | n/a | 1.0 | 1.0 |
| Median latency of the first change (min) | n/a | 0 | 0 |
| Conversations mentioning the fire | 0 | 0 | 0 |
| Replans per agent | 4.0 | 5.0 | 4.9 |
| Scheduled share of actions | 0.75 | 0.70 | 0.73 |
| Model calls per fork | 898 | 1,059 | 808 |

Reading:

* The forks behaved as designed: every condition shares the same state at 10:00 (checked
  in `tests/test_fork.py`), `control` shows no fire-related change, and in both fire
  conditions the one agent present in the cafe perceived the fire at 10:05 and changed course
  in the same minute (the mock reacts to anything "burning" by rule, so the latency is a
  pipeline check, not a finding).
* **Word of the fire did not spread**: no conversation in the two-hour window mentioned it.
  The mock's dialogue shares only authored seeds, inner-voice statements and statements heard
  from third parties with importance ≥ 6; a directly observed event is never brought up. This
  is a documented limitation of the fixture, and exactly the measure (`adaptation_mentions`,
  plus the belief ledger) that a real model should move.
* The **hourly-only planner** adapted identically (same perceiver, same latency, one extra
  replan per affected agent) while making 24% fewer calls than the full hierarchy, because it
  neither decomposes hour blocks nor regenerates tasks after the reaction. The hypothesis
  that it "reacts as often but regenerates fewer tasks" held for the mock.
* Seeds 7–9 changed nothing in these forks: with the mock, the post-fork continuation is
  determined by the prompts, which the seed only perturbs through sampled choices that did
  not arise in this window.

**Limitations.** The mock reacts to "burning" by rule, so the reaction itself is not a finding;
whether the fire spreads by word of mouth depends on the mock's news rule, which only shares
high-importance seeds and statements; four hours is a short window.

---

## What the three experiments established

1. The pipeline runs end to end on all three designs (fresh runs, forks, interventions,
   named metrics, determinism check) and every number traces to a per-run JSON.
2. Where the mechanism is mechanical (forgetting exclusions, fork identity, reaction to a
   perceived event, tie formation from encounters) the measures moved exactly as the mechanism
   implies; where the outcome depends on model behavior (spreading news of a fire, retrieving
   paraphrased facts, social memory changing who talks to whom) the mock showed the floor or
   the no-op the fixture guarantees, which is the point at which a real model is needed.
3. Two measurement lessons were recorded for real runs: the planted-fact probe needs k = 30
   (now reported) to see old-fact effects, and record-based network density must be reported
   with its tie threshold fixed in advance.
