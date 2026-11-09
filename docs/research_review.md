# Research review: what the literature says and how it shaped the platform

This review covers the work that informed the research extensions in Hearthside (see
[`research_platform.md`](research_platform.md)). It separates **established findings**
(peer-reviewed, or replicated preprints) from **positions and preprints** and from
**our own speculation**. References were verified against their primary pages on
2026-11-09; status tags: [PR] peer-reviewed venue, [Pre] preprint, [TR] technical report or
blog, [SW] software. Nothing here reports results we did not run.

## 1. Generative agents and their descendants

**Generative Agents** (Park et al., UIST 2023 [PR], arXiv 2304.03442) introduced the
memory-stream / reflection / planning architecture that Hearthside reproduces, evaluated it
with matched-history interviews rated by humans, and reported information diffusion,
relationship-network density and party attendance in a 25-agent town. The same group's
**Generative Agent Simulations of 1,000 People** (Park et al., 2024 [Pre], arXiv 2411.10109)
grounded agents in two-hour interviews with real participants and reproduced General Social
Survey answers at about 85% of the participants' own test-retest consistency, which is the
clearest individual-level validation standard available; it also showed that interview
grounding reduces demographic-stereotype bias relative to persona prompts. **Social
Simulacra** (Park et al., UIST 2022 [PR]) is the precursor for populating prototypes.

**Concordia** (Vezhnevets et al., 2023 [TR], arXiv 2312.03664; v2 "Multi-Actor Generative AI
as a Game Engine", 2025 [Pre], arXiv 2507.08892; code [SW]) frames generative agent-based
modeling around a *Game Master* that adjudicates what actions do, with agents built from
composable components. Its lesson for this project is architectural: cognition should be
composed of swappable components with an explicit environment arbiter, so that experiments
can vary one component at a time. Hearthside already had a strict engine arbiter; the
research platform adds component-level switches (forgetting, planner depth, social memory)
rather than a new framework.

**Humanoid Agents** (Wang, Chiu & Chiu, EMNLP 2023 demo [PR]) added needs, emotion and a
relationship *closeness* value to generative agents, updated after conversations. Our
relationship record (familiarity, valence) follows that idea but makes the update rules
explicit and logs every update, so the network can be reconstructed and audited.

## 2. Social intelligence evaluation

**SOTOPIA** (Zhou et al., ICLR 2024 [PR]) evaluates language agents in goal-driven social
scenarios with multi-dimensional scores (goal completion, believability, knowledge,
relationship, social rules, secrets, financial). **SOTOPIA-π** (Wang et al., ACL 2024 [PR])
trains agents on such episodes and documents that an LLM evaluator overestimates socially
trained agents. **"Is this the real life?"** (Zhou et al., EMNLP 2024 [PR]) is the most
relevant methodological warning: when one model scripts every party ("omniscient"
simulation) success is inflated relative to information-asymmetric simulation where each
agent sees only its own state. Hearthside's engine is information-asymmetric by
construction; the belief ledger and Theory-of-Mind probe added here make that asymmetry
measurable instead of merely enforced.

## 3. Large-scale social simulation

**AgentSociety** (Piao et al., 2025 [Pre]; v2 2026 [Pre]) runs ten thousand or more agents
with needs, emotion and cognition layers and reports polarization, UBI and disaster-shock
experiments; **OASIS** (Yang et al., 2024 [Pre]) and **Y Social** (Rossetti et al., 2024
[Pre]) simulate social-media platforms; **Project Sid** (Altera, 2024 [TR]) reports role
specialization and cultural transmission in Minecraft societies; **GenSim** (Tang et al.,
2024 [Pre]) adds error correction. Common to all is population-level analysis of emergent
structure from local interactions, with experiment designs that vary environmental
conditions rather than script outcomes. Hearthside is small (3–35 agents) and grounded in a
tile map; what it takes from this line is the *design* of experiments (conditions,
interventions, population-level measures) and the insistence on logging enough to audit
them. **CAMEL**, **MetaGPT** and **AutoGen** ([PR]) are task-oriented multi-agent
frameworks; they matter here only as evidence that role conditioning and structured
communication are robust engineering patterns.

## 4. Validation: when LLM agents stand in for humans

The evidence on LLMs as human proxies is mixed and must be reported as such. **Argyle et
al.** (Political Analysis 2023 [PR]) and **Aher, Arriaga & Kalai** (ICML 2023 [PR]) showed
that conditioned models reproduce some human distributions and classic experiments, with
Aher et al. naming a "hyper-accuracy distortion". **Santurkar et al.** (ICML 2023 [PR])
and **Bisbee et al.** (Political Analysis 2024 [PR]) showed persistent opinion misalignment
and that about half of regression coefficients from synthetic survey data diverge from the
real ones. **Wang, Morgenstern & Dickerson** (Nature Machine Intelligence 2025 [PR]) showed
misportrayal and flattening of identity groups. **Dillion et al.** (TiCS 2023 [PR]) argue
for supplementing, not replacing, participants. Position papers from 2025–2026 (**Anthis et
al.** [Pre]; **Wu et al.**, ICML 2026 position [PR]; **Ye et al.**, 2026 [workshop])
converge on the same operational advice: state the boundary of what a simulation can
support, audit robustness to persona format and framing, and validate against human data
before drawing claims. **Tomašević et al.** (2025 [Pre]) replicated a forum simulation 30
times against real data and found activity matched while toxicity diverged; **Sarangi et
al.** (2026 [Pre]) propose a modular configuration standard for reproducible LLM social
simulations. **Schröder et al.** (2025 [Pre]) report that meaning-changing rewordings
expose gaps between model and human responses.

Consequences adopted here: every report labels mock, replayed and live runs; no claim of
human validity is made; the experiment runner records hypotheses before running, keeps the
run as the unit of analysis, and adds a determinism check; the belief and behavior measures
are mechanical (computed from records), so they cannot be inflated by an LLM judge.

## 5. Memory architectures and forgetting

**CoALA** (Sumers et al., TMLR 2024 [PR]) gives the working/episodic/semantic/procedural
taxonomy that most agent memory systems now use; Hearthside's observation/reflection/plan
kinds map onto episodic, semantic (derived) and procedural-intention memory. **Reflexion**
(Shinn et al., NeurIPS 2023 [PR]) showed that stored verbal self-reflections improve later
decisions, the same mechanism as the paper's reflection. **MemGPT**/Letta (2023 [Pre]/[SW]),
**MemoryBank** (Zhong et al., AAAI 2024 [PR]), **A-Mem** (Xu et al., NeurIPS 2025 [PR]),
**HippoRAG** (Gutiérrez et al., NeurIPS 2024 [PR]) and **Mem0** (2025 [Pre]) explore paging,
Ebbinghaus-style strengthening and forgetting, note linking and graph retrieval. The
controlled-forgetting mechanism added here follows the cognitive-science root of
MemoryBank's idea: **Anderson & Schooler** (Psychological Science 1991 [PR]) showed that
human retention follows the statistics of environmental need and derived ACT-R's base-level
activation, `ln Σ tⱼ^-d`; **Anderson et al.** (Psychological Review 2004 [PR]) is the
integrated architecture, and **Murre & Dros** (PLOS ONE 2015 [PR]) replicate the
Ebbinghaus curve. We implement activation over a memory's creation and last-access traces
and treat sub-threshold memories as inaccessible rather than deleted, which keeps the stream
append-only and the exclusions auditable.

## 6. Theory of Mind

Whether LLMs have Theory of Mind is contested: **Kosinski** (PNAS 2024 [PR]) reports
GPT-4 passing 75% of false-belief tasks; **Ullman** (2023 [Pre]) shows trivial alterations
break them; **Sap et al.** (EMNLP 2022 [PR]) found earlier models near chance; **Strachan et
al.** (Nature Human Behaviour 2024 [PR]) found GPT-4 at human level on most tests but not
faux pas. For simulations the decisive benchmark is **FANToM** (Kim et al., EMNLP 2023 [PR]):
information-asymmetric conversations in which a model must track who knows what, where no
model showed coherent ToM. **Li et al.** (EMNLP 2023 [PR]) showed that explicit belief-state
representations improve LLM cooperation, and **Hypothetical Minds** (Cross et al., ICLR
2025 [PR]) that natural-language hypotheses about other agents help in Melting Pot. Our
belief ledger and probe adopt FANToM's logic in a running town: the evaluator knows, from
transcripts, who was told what, and asks each agent what others know; answers are scored
against both the agent's grounds and the other agent's truth, yielding over-attribution and
under-attribution rates.

## 7. Emergent conventions, norms and cooperation

**Ashery, Aiello & Baronchelli** (Science Advances 2025 [PR]) showed naming-game conventions
and collective bias emerging in LLM populations, with committed minorities tipping them;
**Ren et al.** (IJCAI 2024 [PR], CRSEC) built norm creation, spreading, evaluation and
compliance into Smallville-style agents and observed conflicts declining as norms formed;
**Chuang et al.** (Findings of NAACL 2024 [PR]) found a truth-seeking bias driving
consensus in opinion dynamics; **Perez et al.** (2024 [Pre]) provide a transmission-chain
framework; **Welfare Diplomacy** (Mukobi et al., 2023 [Pre]), **Abdelnabi et al.** (NeurIPS
2024 [PR]) and **Melting Pot** (Agapiou et al., 2022 [TR]) evaluate cooperation. The common
design is to fix local rules and vary conditions, then measure population structure.
Hearthside's social-network and adaptation experiments follow that pattern; norm emergence
itself is proposed below rather than implemented.

## 8. Information diffusion

**S³** (Gao et al., 2023 [Pre]) and **Törnberg et al.** (2023 [Pre]) simulate propagation
on networks and the effect of feed algorithms; **OASIS** and **Y Social** scale this up. The
paper's own party and candidacy diffusion measures remain the backbone here, extended by the
belief ledger's per-exposure provenance and detail values.

## 9. Persona consistency

**Li et al.** (COLM 2024 [PR]) quantify instruction and persona drift within a few dialogue
turns; **Character-LLM** (EMNLP 2023 [PR]), **RoleLLM** (Findings of ACL 2024 [PR]),
**InCharacter** (ACL 2024 [PR]) and **Jiang et al.** (NeurIPS 2023 [PR]) evaluate character
fidelity with interviews and personality inventories. Hearthside's matched-history interviews
and the new behavioral measures (scheduled share, plan adherence) are consistency measures
that need no judge; an inventory-based persona-drift measure is proposed below.

## 10. Reproducibility and judges

**He** (Thinking Machines, 2025 [TR]) traces inference non-determinism to batch-variant
kernels; **Atil et al.** (2024 [Pre]) show temperature-zero runs are not deterministic;
**Sclar et al.** (ICLR 2024 [PR]) show large accuracy swings from prompt formatting alone.
**Zheng et al.** (NeurIPS 2023 [PR]) and **Wang et al.** (ACL 2024 [PR]) document position
and verbosity bias in LLM judges. Hearthside already hashed prompts and recorded served
models; the platform adds a manifest section stating what the seed controls per provider
and an optional determinism check in every experiment. The LLM judge remains labeled
exploratory.

## 11. Explainability

**Turpin et al.** (NeurIPS 2023 [PR]), **Lanham et al.** (2023 [Pre]) and **Chen et al.**
(2025 [Pre]) show that models' stated reasoning often omits the factors that drove the
answer. The platform therefore exposes *recorded* evidence (percepts, retrieved memories
with scores, calls and outcomes) and does not generate explanations after the fact; where a
model gives a reason inside a decision (the reaction prompt's `reason` field) it is shown
as the model's stated reason at the time, not as a cause.

## 12. Feature prioritization

Each candidate from the brief was scored 1–5 on research contribution (R), practical
usefulness (U), feasibility in this codebase (F), performance impact (P; 5 = negligible) and
evaluation potential (E). Implemented items are marked ✔.

| Feature | R | U | F | P | E | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Social memory with interpretable rules and event log ✔ | 5 | 5 | 5 | 5 | 5 | Implemented (`social/`). Needed by experiment B; no model calls unless appraisal is on. |
| Belief ledger and Theory-of-Mind probe ✔ | 5 | 4 | 4 | 5 | 5 | Implemented (`cognition/beliefs.py`, `evaluation/tom.py`). |
| Controlled forgetting (ACT-R activation) ✔ | 4 | 4 | 5 | 5 | 5 | Implemented as an auditable eligibility filter. |
| Hourly-only planner ablation ✔ | 3 | 4 | 5 | 5 | 4 | Implemented; gives a graded planning baseline and fewer calls. |
| Behavior, adaptation and retrieval-probe metrics ✔ | 4 | 5 | 5 | 5 | 5 | Implemented; all computed from records. |
| Counterfactual forks and per-condition interventions ✔ | 5 | 5 | 4 | 5 | 5 | Implemented (`simulation/fork.py`, `ga fork`, protocol `fork_from`). |
| Metric registry, generic reports, determinism check ✔ | 4 | 5 | 5 | 5 | 5 | Implemented. |
| Decision records and research dashboards ✔ | 3 | 5 | 4 | 5 | 3 | Implemented in the no-build viewer. |
| Relationship records informing prompts ✔ | 3 | 3 | 5 | 4 | 4 | Implemented behind `social.inform_prompts` (off by default; fidelity class X). |
| Explicit long-term goal objects with priorities | 4 | 3 | 2 | 3 | 3 | Deferred: would change the paper's planning prompts; proposed below as a goal ledger derived from plans. |
| Resource system and competition scenarios | 4 | 3 | 2 | 3 | 4 | Deferred: needs scenario authoring and new world-state semantics. |
| Norm emergence modules (CRSEC-style) | 5 | 3 | 2 | 2 | 4 | Proposed (below); adds several prompts per step. |
| Post-hoc LLM explanations of decisions | 1 | 3 | 5 | 4 | 2 | Rejected on the faithfulness evidence (§11); recorded evidence instead. |
| Asynchronous engine | 2 | 4 | 2 | 5 | 1 | Deferred: wall time is model latency; snapshot semantics would need redesign. |

## 13. Original research extensions proposed (not implemented)

### 13.1 Metacognitive confidence and calibration

* **Motivation.** Agents act on retrieved memories without any estimate of how complete
  or reliable they are; ToM probes show over-attribution (claiming others know what they
  do not). A confidence signal, if calibrated, would let agents hedge, ask, or verify.
* **Literature.** Calibration of LLM verbalized confidence (Lin et al. 2022, "Teaching
  Models to Express Their Uncertainty in Words", TMLR; Kadavath et al. 2022, "Language
  Models (Mostly) Know What They Know", arXiv); FANToM (Kim et al. 2023) for the
  information-asymmetric setting.
* **Architecture.** Add a `confidence` field to the interview, talk-decision and dialogue
  output schemas; derive a mechanical prior from the retrieval trace (share of the budget
  used, top score, forgetting exclusions); store both. The belief ledger already supplies
  ground truth, so calibration curves (stated confidence versus correctness) follow directly.
* **Impact.** A per-agent calibration score and a test of whether confidence-aware prompts
  reduce over-attribution and unsupported claims.
* **Evaluation.** Expected calibration error on ToM and diffusion probes; ablation with and
  without the confidence field; comparison of mechanical prior versus stated confidence.
* **Complexity.** Low–medium (schema fields, two prompts, one metric).
* **Limitations.** Stated confidence may be post-hoc and prompt-sensitive (Sclar et al.
  2024); the mechanical prior depends on embedding quality.

### 13.2 Social knowledge graph with provenance

* **Motivation.** The belief ledger tracks seeded topics only. A general graph of (agent,
  claim, source, time) would let any statement be traced through the town, including
  distortions.
* **Literature.** Knowledge-graph memory for agents (HippoRAG 2024; A-Mem 2025); rumor and
  diffusion modeling (S³ 2023; Chuang et al. 2024).
* **Architecture.** A `claims` table filled by an extraction prompt run over each
  utterance (subject, predicate, object, polarity), linked to the memory ids of speaker and
  listener; graph queries for provenance chains; a viewer tab showing a claim's spread.
* **Impact.** Measures of distortion (claim drift along chains), rumor lifetime, and
  per-agent source reliability.
* **Evaluation.** Precision of extraction against hand-labeled utterances; agreement of the
  graph's diffusion counts with the regex-based topic evidence already in the evaluator.
* **Complexity.** Medium (one prompt per utterance, a new table, graph utilities).
* **Limitations.** Extraction errors compound along chains; mock runs would need a
  keyword extractor.

### 13.3 Norm emergence and sanctioning

* **Motivation.** The paper observed norm violations (closed stores, private rooms) and
  Hearthside enforces norms mechanically (`strict-v1`). Whether norms can *emerge* from
  agents' reactions and sanctions is an open question CRSEC (Ren et al. 2024) addressed with
  dedicated modules.
* **Literature.** Ren et al. 2024 (IJCAI); Ashery et al. 2025 (Science Advances);
  Melting Pot substrates on sanctioning.
* **Architecture.** Turn `constraints.policy` into a three-way switch (none, strict,
  emergent). Under *emergent*, violations are perceived by bystanders as events ("X entered
  the closed store"); a reaction may `sanction` (a new decision type) which creates a
  statement memory in the violator; a norm ledger counts violations, sanctions and
  compliance per rule over time.
* **Impact.** Conditions under which violation rates fall without enforcement; the role of
  network density (from the social memory) in norm spread.
* **Evaluation.** Violation rate over time by condition; sanction–compliance latency;
  comparison with `strict-v1` and `none` baselines using the existing norm-violation
  detector in the failure taxonomy.
* **Complexity.** Medium–high (perception of violations, new decision type, prompts).
* **Limitations.** Mock agents cannot show the effect; needs real models and many runs.

### 13.4 Goal ledger and goal-conditioned adaptation

* **Motivation.** Long-term goals live in free text (`currently`). Measuring goal
  completion or goal conflict needs goals as objects.
* **Literature.** Hierarchical planning in the paper; goal-directed evaluation in SOTOPIA
  (goal completion dimension); Voyager's skill library as persistent objectives.
* **Architecture.** A `goals` list per agent in the scenario (text, priority, deadline,
  success pattern) rendered into the day-plan prompt only; a mechanical matcher scores
  each hour block and executed action against goals; the adaptation metric then reports
  which goals an intervention displaced.
* **Impact.** Goal completion and goal-conflict measures, and a principled definition of
  "plan feasibility" (planned goal time versus available time).
* **Evaluation.** Agreement of the matcher with human labels on a sample; ablation of goal
  rendering in the prompt.
* **Complexity.** Low–medium.
* **Limitations.** Keyword matching of goals is brittle; the paper's prompts change when
  goals are rendered (fidelity class X).

### 13.5 Cross-model behavioral replication harness

* **Motivation.** The validation literature (§4) shows results depend on the model and the
  prompt format. A harness that re-runs one protocol across models and formats, with the
  determinism check, would quantify that dependence for this town.
* **Literature.** Sclar et al. 2024 (format sensitivity); Atil et al. 2024 (stability);
  Ye et al. 2026 (robustness audits).
* **Architecture.** A protocol field `model_matrix` listing provider/model pairs and prompt
  template versions; the runner expands conditions × models; the report adds a
  model-by-condition table and a robustness summary (sign agreement of effects across
  models).
* **Impact.** Direct evidence of which effects in experiments A–C survive a change of model
  or template.
* **Evaluation.** Sign and rank agreement of primary outcomes across models; variance
  decomposition (condition versus model versus seed).
* **Complexity.** Low (runner expansion) but high cost (calls scale with models).
* **Limitations.** Cost; template changes alter prompt hashes and break replay across
  versions by design.

## 14. Research ethics and interpretation

Agents here are synthetic characters built from the paper's authored personas. Nothing in
the platform presents generated populations as representative of real demographic groups,
and the reports repeat that plausibility is not validity (Wang et al. 2025; Bisbee et al.
2024). Prompts, outputs and derived measures are logged so that any claim can be traced to
its records.

## References (verified)

1. Park, O'Brien, Cai, Morris, Liang, Bernstein. Generative Agents: Interactive Simulacra of Human Behavior. UIST 2023. https://arxiv.org/abs/2304.03442
2. Park, Zou, Shaw, Hill, Cai, Morris, Willer, Liang, Bernstein. Generative Agent Simulations of 1,000 People. arXiv 2411.10109, 2024.
3. Park, Popowski, Cai, Morris, Liang, Bernstein. Social Simulacra. UIST 2022. https://arxiv.org/abs/2208.04024
4. Vezhnevets et al. Generative agent-based modeling with actions grounded in physical, social, or digital space using Concordia. arXiv 2312.03664, 2023. Code: https://github.com/google-deepmind/concordia
5. Vezhnevets et al. Multi-Actor Generative Artificial Intelligence as a Game Engine. arXiv 2507.08892, 2025.
6. Zhou et al. SOTOPIA: Interactive Evaluation for Social Intelligence in Language Agents. ICLR 2024. https://arxiv.org/abs/2310.11667
7. Wang et al. SOTOPIA-π. ACL 2024. https://aclanthology.org/2024.acl-long.698
8. Zhou, Su, Eisape, Kim, Sap. Is this the real life? Is this just fantasy? The Misleading Success of Simulating Social Interactions With LLMs. EMNLP 2024. https://aclanthology.org/2024.emnlp-main.1208
9. Piao et al. AgentSociety. arXiv 2502.08691, 2025; AgentSociety 2, arXiv 2607.11895, 2026. Code: https://github.com/tsinghua-fib-lab/agentsociety
10. Yang et al. OASIS: Open Agent Social Interaction Simulations with One Million Agents. arXiv 2411.11581, 2024.
11. Altera.AL. Project Sid: Many-agent simulations toward AI civilization. arXiv 2411.00114, 2024.
12. Tang et al. GenSim. arXiv 2410.04360, 2024.
13. Rossetti et al. Y Social. arXiv 2408.00818, 2024.
14. Wang, Chiu, Chiu. Humanoid Agents. EMNLP 2023 System Demonstrations. https://aclanthology.org/2023.emnlp-demo.15
15. Li et al. CAMEL. NeurIPS 2023. 16. Hong et al. MetaGPT. ICLR 2024. 17. Wu et al. AutoGen. COLM 2024, arXiv 2308.08155.
18. Argyle et al. Out of One, Many. Political Analysis 31(3), 2023.
19. Aher, Arriaga, Kalai. Using Large Language Models to Simulate Multiple Humans. ICML 2023. https://arxiv.org/abs/2208.10264
20. Santurkar et al. Whose Opinions Do Language Models Reflect? ICML 2023.
21. Bisbee et al. Synthetic Replacements for Human Survey Data? Political Analysis 32(4), 2024.
22. Anthis et al. Position: LLM Social Simulations Are a Promising Research Method. arXiv 2504.02234, 2025.
23. Gao et al. Large language models empowered agent-based modeling and simulation: a survey. Humanities & Social Sciences Communications 11, 2024.
24. Ziems et al. Can Large Language Models Transform Computational Social Science? Computational Linguistics 50(1), 2024.
25. Wang, Morgenstern, Dickerson. Large language models that replace human participants can harmfully misportray and flatten identity groups. Nature Machine Intelligence 7, 2025.
26. Dillion, Tandon, Gu, Gray. Can AI language models replace human participants? Trends in Cognitive Sciences 27(7), 2023.
27. Horton. Large Language Models as Simulated Economic Agents. NBER WP 31122, 2023. 28. Manning, Zhu, Horton. Automated Social Science. arXiv 2404.11794, 2024.
29. Xie, Chen et al. Can Large Language Model Agents Simulate Human Trust Behavior? NeurIPS 2024.
30. Schröder et al. Large Language Models Do Not Simulate Human Psychology. arXiv 2508.06950, 2025.
31. Wu et al. Position: LLM-Based Social Simulations Require a Boundary. arXiv 2506.19806; ICML 2026.
32. Ye, Cao, Chen, Ferrara. Stop Drawing Scientific Claims from LLM Social Simulations Without Robustness Audits. arXiv 2605.18890, 2026.
33. Tomašević et al. Towards Operational Validation of LLM-Agent Social Simulations. arXiv 2508.21740, 2025.
34. Sarangi et al. EASE Configuration Facilitates A Reproducible Science of LLM Social Simulations. arXiv 2605.30258, 2026.
35. Packer et al. MemGPT. arXiv 2310.08560, 2023; Letta code https://github.com/letta-ai/letta
36. Xu et al. A-Mem: Agentic Memory for LLM Agents. NeurIPS 2025.
37. Zhong et al. MemoryBank. AAAI 2024.
38. Shinn et al. Reflexion. NeurIPS 2023. https://arxiv.org/abs/2303.11366
39. Sumers, Yao, Narasimhan, Griffiths. Cognitive Architectures for Language Agents. TMLR 2024. https://arxiv.org/abs/2309.02427
40. Wang et al. Voyager. TMLR 2024. 41. Gutiérrez et al. HippoRAG. NeurIPS 2024. 42. Chhikara et al. Mem0. arXiv 2504.19413, 2025.
43. Anderson, Schooler. Reflections of the Environment in Memory. Psychological Science 2(6), 1991.
44. Anderson et al. An Integrated Theory of the Mind. Psychological Review 111(4), 2004.
45. Murre, Dros. Replication and Analysis of Ebbinghaus' Forgetting Curve. PLOS ONE 10(7), 2015.
46. Kosinski. Evaluating large language models in theory of mind tasks. PNAS 121(45), 2024.
47. Ullman. Large Language Models Fail on Trivial Alterations to Theory-of-Mind Tasks. arXiv 2302.08399, 2023.
48. Sap, Le Bras, Fried, Choi. Neural Theory-of-Mind? EMNLP 2022.
49. Gandhi et al. Understanding Social Reasoning in Language Models with Language Models (BigToM). NeurIPS 2023 D&B.
50. Kim et al. FANToM. EMNLP 2023. https://aclanthology.org/2023.emnlp-main.890
51. Strachan et al. Testing theory of mind in large language models and humans. Nature Human Behaviour 8, 2024.
52. Cross et al. Hypothetical Minds. ICLR 2025.
53. Li et al. Theory of Mind for Multi-Agent Collaboration via Large Language Models. EMNLP 2023. https://arxiv.org/abs/2310.10701
54. Mukobi et al. Welfare Diplomacy. arXiv 2310.08901, 2023. 55. Abdelnabi et al. Cooperation, Competition, and Maliciousness. NeurIPS 2024 D&B. 56. Agapiou et al. Melting Pot 2.0. arXiv 2211.13746.
57. Ren et al. Emergence of Social Norms in Generative Agent Societies (CRSEC). IJCAI 2024. https://arxiv.org/abs/2403.08251
58. Perez et al. Cultural evolution in populations of Large Language Models. arXiv 2403.08882, 2024.
59. Ashery, Aiello, Baronchelli. Emergent social conventions and collective bias in LLM populations. Science Advances 11(20), 2025.
60. Chuang et al. Simulating Opinion Dynamics with Networks of LLM-based Agents. Findings of NAACL 2024.
61. Gao et al. S³. arXiv 2307.14984, 2023. 62. Törnberg et al. Simulating Social Media Using Large Language Models to Evaluate Alternative News Feed Algorithms. arXiv 2310.05984, 2023.
63. Li et al. Measuring and Controlling Instruction (In)Stability in Language Model Dialogs. COLM 2024, arXiv 2402.10962.
64. Shao et al. Character-LLM. EMNLP 2023. 65. Wang et al. RoleLLM. Findings of ACL 2024. 66. Wang et al. InCharacter. ACL 2024. 67. Jiang et al. Evaluating and Inducing Personality in Pre-trained Language Models. NeurIPS 2023.
68. He. Defeating Nondeterminism in LLM Inference. Thinking Machines Lab, 2025. https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
69. Atil et al. LLM Stability: A detailed analysis with some surprises. arXiv 2408.04667.
70. Sclar et al. Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design. ICLR 2024.
71. Zheng et al. Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena. NeurIPS 2023 D&B. 72. Wang et al. Large Language Models are not Fair Evaluators. ACL 2024.
73. Turpin, Michael, Perez, Bowman. Language Models Don't Always Say What They Think. NeurIPS 2023. 74. Lanham et al. Measuring Faithfulness in Chain-of-Thought Reasoning. arXiv 2307.13702, 2023. 75. Chen et al. Reasoning Models Don't Always Say What They Think. arXiv 2505.05410, 2025.
76. Lin, Hilton, Evans. Teaching Models to Express Their Uncertainty in Words. TMLR 2022. 77. Kadavath et al. Language Models (Mostly) Know What They Know. arXiv 2207.05221, 2022. (Cited in §13.1 only; not re-verified in this review.)
