# Presenting Hearthside

Hearthside is a town simulation with residents who remember, plan, and interact. A good demonstration shows both the town and the recorded evidence behind one resident's decision.

## GitHub About

**Project name:** Hearthside

**Suggested repository name:** `hearthside`

**Description:**

> A local town simulation with residents who remember, plan, and interact. Explore the town, build for its residents, and inspect the memories behind their decisions.

**Topics:** `generative-agents`, `agent-simulation`, `local-llm`, `ollama`, `threejs`, `react`, `python`, `human-ai-interaction`

The current repository address is `nathanu1/artsoce`. The README and application use Hearthside as the project name. If the repository address changes, update the clone URL and the repository links in `pyproject.toml`.

## Portfolio description

> **Hearthside — Generative agent town simulation**
>
> I built Hearthside to explore how memory, reflection, and planning shape interactions between simulated residents. It combines a Python simulation engine with a React and Three.js town interface, local model support through Ollama, and an inspector for memories, retrieval scores, plans, and model calls. Saved runs support checkpoint recovery and replay. The project reproduces the architecture from Park et al.'s Generative Agents paper and extends it with town-building interactions and a 35-resident neighborhood.

**Compact version:**

> A town simulation built with Python, React, and Three.js. Residents use memory, reflection, and planning to decide what to do, while an inspector exposes the recorded state and model calls. Supports local models, experiments, and replay.

## A 90-second walkthrough

| Time | Show | Explain |
| --- | --- | --- |
| 0–15 s | The town and a resident's current activity | “Hearthside is a town simulation. Each resident has memories and a plan for the day.” |
| 15–35 s | A resident card and a recorded conversation | “Conversations become part of the resident's memory, so I can follow an exchange beyond the chat window.” |
| 35–55 s | The inspector's Memories and Retrieval tabs | “Here are the stored observations and the scores used to retrieve them for a decision.” |
| 55–70 s | A daily plan or reflection with source memories | “Planning turns a day into smaller tasks. Reflections connect experiences and retain links to their evidence.” |
| 70–90 s | A request, a placed object, and the saved-run controls | “The town-building layer lets me change the residents' surroundings. I can record the run and revisit it without new model calls.” |

Use the offline demo to explain the interface and mechanics. Identify it as MOCK when showing it. Use a saved local-model run when discussing generated dialogue. The local-run figures in the README measure execution and model usage; human-rated believability has not been established.

## Start a demonstration

From the repository root, after installing the project:

```bash
ga play --config configs/town_mock.yaml --open
```

Try these steps:

1. Pause the town and select a resident.
2. Read the resident's current activity and plan.
3. Chat with the resident, then open the research inspector.
4. Find the exchange in the resident's memories and inspect a retrieval trace.
5. Return to the town, ask for a wish, and open Build and Decorate.
6. Place an item, then show how the run can be saved and replayed.

The town guide documents [controls and interaction channels](game.md). The [walkthrough](walkthrough.md) supplies a worked memory-to-plan example for technical questions.

### Make a portable recording

The included script records a deterministic mock morning with chats, a gift, building, and a delivered request:

```bash
uv run python examples/record_demo_town.py runs/demo-town
cd frontend
npm ci
npm run build:demo
cd ..
uv run ga export-demo --run-dir runs/demo-town --out frontend/dist-demo
python -m http.server -d frontend/dist-demo 8090
```

Open [localhost:8090/demo.html](http://127.0.0.1:8090/demo.html). The exported page plays the recording and inspector data without a running simulation or model. It still needs to be served over HTTP so its data files can load.

For a saved local-model town, replace `runs/demo-town` in the export command with that run's directory. Read [the local-run guide](game.md#running-it) before scaling up the population.

## Visuals for the project page

The README uses screenshots captured from the running offline town:

- [Town view](assets/hearthside-town.png): the setting, residents, and town controls.
- [Memory inspector](assets/hearthside-inspector.png): a resident's recorded observations.

Both show the actual application. Their MOCK labels identify the model used for the demonstration.

When recording a video, spend most of the time on one resident and one exchange. Follow it from the town into memory and retrieval. A concrete example makes the project easier to understand than a tour of every tab.

## Questions to be ready for

| Question | Evidence to show |
| --- | --- |
| What came from the original paper? | [Reproduction specification](reproduction_spec.md), [NOTICE](../NOTICE), and the upstream source pin. |
| What did this project add? | Local-model adapters, recorded replay and inspection, town-building interactions, and the additional neighborhood. |
| How do you keep agents' knowledge separate? | Memory isolation, each agent's spatial memory, and tests for evaluator-only information staying out of prompts. |
| What happens when a model returns invalid output? | Schema validation, the repair attempt, and the recorded failure in the call ledger. |
| What has actually been tested? | The development checks and the documented local-run measurements in the town guide. |

[Nathan Yang (@nathanu1)](https://github.com/nathanu1) is the project creator and maintainer. Claude is credited as an AI development contributor in [CONTRIBUTORS.md](../CONTRIBUTORS.md).
