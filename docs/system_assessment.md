# Existing system assessment

An inspection of the Hearthside repository as it stood before the research platform work
(commit `09f87ee`), written to answer one question: what does the implementation already do,
and where does it stop short of a platform for systematic experiments on generative agents?
Every statement below was checked against the code, not the README.

## 1. What the project is

Hearthside is a faithful, well-engineered reimplementation of *Generative Agents* (Park et
al., UIST 2023) with a town-game front end. The Python core (about 16,000 lines in
`src/generative_agents/`) is organized as a pipeline whose stages match the paper:

| Stage | Module | Fidelity to the paper and released code |
| --- | --- | --- |
| Perception | `world/perception.py` | Released-code rules: square vision, same arena, attention bandwidth, retention dedupe. |
| Memory stream | `memory/store.py`, `schemas.py` | Append-only SQLite stream; every record has kind, origin (ten provenance classes), timestamps, importance, embedding, evidence links, subject–predicate–object triple, metadata. |
| Retrieval | `memory/retrieval.py` | Paper's three-factor score with min–max normalization and token-budget prefix; released-code compatibility mode; every retrieval writes a trace with per-candidate components. |
| Importance | `cognition/importance.py` | Paper anchors; batched statement scoring; idle shortcut. |
| Reflection | `cognition/reflection.py` | Threshold trigger, three questions, insights that must cite supplied memories; citations validated structurally (exist, same owner, supplied, acyclic). |
| Planning | `cognition/planning.py` | Day plan → validated hour schedule → just-in-time 5–15 minute tasks; insertion and replanning after interruptions. |
| Reacting | `cognition/reaction.py` | One focal percept per step; two-query context; talk-before-react ordering as in the released code. |
| Dialogue | `cognition/dialogue.py` | Turn by turn, each turn conditioned only on the speaker's memory; private transcripts. |
| World | `world/` | Map hierarchy, navigation, object states with in-use and lasting conditions, ambient events, opening-hours and privacy constraints. |
| Engine | `simulation/engine.py` | Snapshot–decide–commit steps, checkpoints, crash-safe resume, exact replay from the call ledger, budget ceilings, timed snapshots, interventions. |
| Providers | `providers/` | One gateway for every call: versioned prompt templates, JSON-schema validation with one repair, request ledger, pricing; adapters for Anthropic, OpenAI, Ollama, OpenAI-compatible servers and a deterministic mock. |
| Evaluation | `evaluation/` | Matched-history interviews under memory masks, claimed-versus-memory-supported diffusion, relationship probes, physical attendance, failure taxonomy, rank statistics, a reflection on/off experiment runner. |
| Viewer | `viewer/` | Read-only FastAPI app: map replay, retrieval traces with score decomposition, evidence trees, conversations, social measures, interviews, experiment tables. |

Supporting assets: the Smallville data converted to YAML/JSON with provenance, a
64-page reproduction specification that classifies every setting as paper / released code /
engineering / extension, 24 versioned prompt templates each with a recorded example, 189
offline tests, and documentation of three real Llama 3.2 3B runs.

## 2. Strengths worth preserving

* **Information scoping is enforced, not assumed.** Prompts are rendered only from an
  agent's own identity, memories and perceptions; evaluator ground truth (`events.yaml`) is
  loaded for the engine and evaluator only, and a test asserts that probe questions never
  reach a prompt. This is exactly the partial observability a Theory-of-Mind study needs.
* **Everything is recorded.** The call ledger stores every prompt and raw output; retrieval
  traces store every candidate's components; events store decisions with reasons. Replay
  from the ledger is bit-exact and tested.
* **Nothing is fabricated on failure.** A failed model call leaves a visible failure (no plan,
  no insight, a failed action) rather than a made-up substitute.
* **Evaluation validates claims against memory.** Diffusion and relationship probes separate
  "claims to know" from "has a received memory", which is the right primitive for measuring
  hallucination in a social simulation.
* **The experiment runner already has the right unit of analysis** (the run), fixed primary
  outcomes, matched seeds and honest statistics.

## 3. Limitations found

| Area | Finding | Consequence for research use |
| --- | --- | --- |
| Social state | There is no in-simulation representation of relationships. Relationships exist only as an *evaluation* (asking "Do you know of X?" on a snapshot). The game layer's "affinity" is a player-facing mechanic. | Social structure cannot be observed as it forms, cannot be compared across conditions without expensive interview probes, and cannot feed back into behavior. |
| Beliefs and Theory of Mind | Agents' knowledge is implicit in their memory streams. There is no ledger of what each agent has grounds to believe about others' knowledge, and no probe of second-order belief. | Questions such as "does A know that B knows?" cannot be asked of the data, and the model's over-attribution of knowledge cannot be measured. |
| Memory variants | Retrieval has two modes (paper, released code) and adjustable weights. There is no forgetting or consolidation mechanism, and the "no memory" and "observations only" conditions exist only for interviews, not for running agents. | Memory-architecture comparisons are limited to weights and reflection on/off. |
| Planning variants | `architecture.planning=false` leaves agents idle; there is no intermediate planner (hour blocks without task decomposition). | "Reactive versus planning" comparisons have no graded baseline. |
| Experiment framework | Outcomes are hard-wired to the party and candidacy events. Conditions are arbitrary overrides, but there is no registry of metrics, no counterfactual design (fork from a shared state), no per-condition interventions, and no documented check of determinism. | Any new question needs code changes to the runner; "same past, different futures" experiments are impossible without manual copying. |
| Behavioral measures | No measures of plan adherence, reactivity, idleness or adaptation latency are computed, although the data to compute them (plans, events, frames) is recorded. | Behavioral consistency and adaptation cannot be compared across conditions. |
| Retrieval accuracy | Retrieval quality is only visible through downstream probes. There is no controlled probe of whether the mechanism returns what it should. | Memory conditions cannot be separated from the model's behavior. |
| Explainability | The viewer shows retrieval traces, evidence trees and call records separately. There is no per-decision view that joins the percept, the retrieval, the calls and the outcome. | Debugging a single decision requires cross-referencing three tabs. |
| Dashboard | Social measures appear only after `ga evaluate`; there is no network-over-time view, no behavior view, and the experiment tab lists fixed columns. | Researchers cannot inspect emergence as it happens or compare arbitrary outcomes. |
| Randomness documentation | The manifest records the seed but not what the seed controls for each provider. | Readers of a report cannot tell what "matched seeds" guarantees. |

Performance and scale: the engine is single-threaded and synchronous; a 25-agent two-day mock
run takes 6.6 minutes, dominated by 33,000 calls, so wall time with real models is set by
model latency, not by the engine. Relationship tracking, as added, is O(interactions), not
O(n²), so it does not change this picture.

## 4. Opportunities that the research platform takes up

1. A **social memory** layer with interpretable update rules and an append-only event log, so
   networks can be reconstructed at any time and ablated (`social.*`).
2. A **belief ledger** computed from each agent's own memories, kept strictly apart from world
   truth, plus an interview-based **Theory-of-Mind probe** scored against grounds and truth.
3. **Controlled forgetting** in retrieval (activation-based, auditable) and an **hourly-only
   planner**, giving graded memory and planning conditions for ablations.
4. **Behavioral, adaptation and retrieval-probe metrics** from recorded data alone.
5. **Counterfactual forks** from snapshots, per-condition interventions, a **metric registry**
   and a determinism check in the experiment runner.
6. A **decision-record view** (recorded evidence only), network, behavior and belief
   dashboards, and a generic experiment comparison.

What was deliberately left alone: the paper-faithful cognitive loop and its defaults (every
extension is off by default or purely observational), the game layer, the provider gateway
and the replay/resume machinery.
