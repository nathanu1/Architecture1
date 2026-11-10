# The town in a tab

A static web page. Someone opens it, presses **Start the town**, and a small town runs on their
own device: the engine, the residents' memories and the language model that does their thinking.
There is no server behind it, no account and no bill, however many people open it, because each
visitor's computer does its own town's work. Nothing a visitor does leaves their device.

It is a third way to reach the same town as the [living town on a model server](deploy.md) and
the [research platform](research_platform.md): the same Python package, the same interface, the
same inspector.

## What a visitor sees

A title screen that is a small 3D world at dusk: the town's name in chunky extruded letters
standing on a paved square, with grass, blossom and autumn trees, lanterns, a cottage, a river
and bridge behind, and the town's three residents beside the letters. The letters drop in when
the page opens and the view drifts slightly with the pointer. Over it sits a small menu: one
row of choices for how the residents think and a **Start** button, with a few words on how big
the one-time download is. While a model downloads the menu shows a progress bar. The browser
keeps the model, so the next visit starts in seconds, and the button then reads **Continue**
next to **New Town** (which asks once more before erasing): the town is saved in the browser
every twenty seconds and when the tab is hidden. A browser that cannot run a model on its
graphics chip gets the model choices greyed out and can still look around.

A new town opens at dawn, at the minute its earliest riser wakes. Everyone else is asleep in
their own bed and gets up at their own hour, plans the day, and goes about it.

The world is built in code from simple shapes (`frontend/src/tab/TitleWorld.ts`), reuses the
town's own resident models, and takes its letter outlines from the town's display font
(`scripts/make-title-font.mjs`). It stays still for people who ask for reduced motion, falls
back to plain large type where 3D drawing is unavailable, and frees its graphics memory before
the town itself starts drawing.

| Choice | Model (WebLLM id) | Download | Graphics memory |
| --- | --- | ---: | ---: |
| Look around | none (scripted residents, placeholder words) | 0 | 0 |
| Small | `Llama-3.2-1B-Instruct-q4f16_1-MLC` | 0.7 GB | 0.9 GB |
| Standard | `Llama-3.2-3B-Instruct-q4f16_1-MLC` | 1.8 GB | 2.3 GB |
| Bright | `Qwen3-4B-q4f16_1-MLC` | 2.3 GB | 3.4 GB |
| Largest | `Llama-3.1-8B-Instruct-q4f16_1-MLC` | 4.5 GB | 5.0 GB |

Memory figures are the runtime's own (`@mlc-ai/web-llm` 0.2.87). On a graphics chip without
half-float support the page loads the full-precision file of the same model (`q4f32_1`, about a
third more memory). `?mind=<id>` in the address starts straight away; any model id from the
runtime's list works there.

## How it works

```
 the page (React, the same interface as the server's)
   │  asks: info, map, poll, actions, inspector paths            answers a question
   ▼                                                              ▲
 engine worker                                                    │
   Pyodide: CPython compiled to WebAssembly                       │
   the generative_agents package, unchanged (game/tab.py)   ──▶  model worker
   SQLite files in the browser's storage (IndexedDB)             WebLLM on WebGPU
```

**The engine is not a port.** `npm run build:tab` puts the Python runtime, three packages
(numpy, pydantic, pyyaml) and this repository's wheel next to the page. The worker loads them
and creates a `TabTown`, which answers what the interface would otherwise fetch from a server.

**Pausing for the model without threads.** The engine is synchronous Python; the model answers
asynchronously in JavaScript; a browser's Python has no threads. The bridge uses what the
engine already guarantees for resume and replay, that a step is a transaction:

1. the engine asks for a completion and the provider raises `Deferred` with the request;
2. the step is rolled back to its last commit and the page gets the question;
3. the model answers, the answer is delivered, the step runs again and now finds it. The
   gateway records it in the call ledger like any call, so the next repetition finds it there
   and moves on to the next question.

A step with k questions runs k+1 times. Measured inside Pyodide: 42 questions cost 3 seconds of
repetition in total, against seconds per question for the model. `tests/test_tab.py` shows the
result is exactly the town a blocking model would have produced (same state hash), and
`npm run test:tab` runs the same check inside the browser's Python runtime.

**Who does the thinking.** The model does. It plans each resident's day, breaks the hours
into actions, chooses where to go, decides how to react to what it sees, and writes every
conversation, reply and reflection. Nothing a resident does comes from a script (the ledger
shows `browser` as the provider of every answer). One model answers one question at a time,
so the tab town (`configs/town_tab.yaml`) keeps the questions few and spread out in ways that
do not script behaviour:

| Setting | What it does | Where |
| --- | --- | --- |
| Days are planned on waking | The paper's agents all plan at the same instant. Here a resident sleeps until their own usual hour ("awakes up around 6am", give or take a few minutes that differ by person and day) and plans the day then. A new town opens at the minute its earliest riser wakes, with everyone else in their own bed. | `planning.at_waking` |
| Nothing lived, nothing summarised | The three self-summaries are written once a resident holds 30 memories beyond the authored ones, and then once a day. Before that the authored identity stands alone. | `summary.min_lived`, `summary.refresh_every_minutes` |
| Importance is read from meaning | A memory's 1 to 10 rating comes from where its embedding sits between everyday and momentous examples, with no model question (below). | `importance.strategy: meaning` |
| One question for a place, kept for the hour | | `location` |
| Settled situations are answered from the record | | `memoize_tasks`, `habit_tasks` |
| Routine sightings are not deliberated twice in an hour | | `reaction.salience_gate` |

Counted on a recorded day with ten residents (the offline model answering, so these are
question counts, not speeds):

| Ten residents | Questions before the first step | Questions in the first game day |
| --- | ---: | ---: |
| The paper's procedure (`?depth=full`) | 115 | 2,126 |
| The tab town's default | 6 | 1,288 |

The largest single stall left is a conversation, which is written in one step (up to about
forty questions when it also sets off a reflection). While it is written the page shows each
line over its speaker's head as soon as it exists, and the banner says who is finding the
words. Every thought is named in plain words ("Maria is planning the day", "Klaus is deciding
where to go").

`?depth=full` in the address follows the paper to the letter: everyone plans at once at seven,
the model rates every memory, summaries are always written. `?depth=words` is the fastest: the
model writes only what a visitor reads and the routine comes from the scripted fixture. The
start menu offers 3, 10 or 25 neighbours.

**Memory by meaning.** A new town with a model for a mind also downloads a small embedding
model (`snowflake-arctic-embed-s`, 130 MB, 384 numbers per text) and runs it in a worker of its
own. Every memory is stored with its vector and recalled by the paper's score: recency,
importance and cosine relevance to the question at hand. Queries carry the instruction the
model's authors prescribe for queries; stored memories do not.

The engine cannot wait for the page inside a step, and a step may need dozens of vectors. So a
text whose vector is not known yet gets a stand-in and is noted; the pass carries on and
gathers every other text it needs; then the whole pass is undone, the page embeds all of them
in one batch, and the pass runs again on the real vectors. Nothing computed from a stand-in is
ever saved (a hook refuses the commit). `tests/test_tab.py` shows the result is exactly the
town whose embedding model answers on the spot, vectors included.

The embedding model is fixed when a town is founded, because the vectors in its store belong
to one model. A town founded with the scripted residents, or on a device where the embedding
model cannot load, searches by shared words instead, and says so in `info.memory`.

**Importance from meaning, checked.** The rating is the mean cosine similarity to sixteen
momentous examples minus the mean to sixteen everyday ones, on a scale that calibrates itself
on those examples (a typical everyday example reads 1, a typical momentous one 8). The examples
were adjusted against two sets of statements rated by hand. On a third set of 20, written and
rated after the examples were fixed, the real embedding model's ratings correlated 0.82 with
the hand ratings, with a mean error of 1.5 points and no overall bias (mean 4.9 against 4.8).
That is one author's small check, not a study: it is a rough stand-in for asking the model,
and `?depth=full` asks the model instead.

**The player comes first.** What the player says or does is its own unit of work: it is
handled ahead of the step, a resident's thought in progress steps aside for it, and the reply
is shown as soon as its own question is answered. A reply is shown once however often the step
behind it is repeated, and a repeated question is asked again, never answered from the record.

## What has been checked, and what has not

| Checked | How |
| --- | --- |
| The engine runs unmodified in the browser's Python | `npm run test:tab` (Node) and headless Chromium |
| Pausing for answers equals a blocking run | `tests/test_tab.py`, state hashes compared |
| Start screen, one-click start, inspector, save and continue after reload | headless Chromium against the built site: town on screen 6 seconds after the click |
| The question-and-answer path between page, engine and a mind | headless Chromium with a stand-in mind |
| A real model's files download and load in the page, and the town asks it its first question | headless Chromium with a software graphics adapter and a 207 MB test model (`?mind=SmolLM2-360M-Instruct-q4f32_1-MLC`) |
| The real embedding model runs in the page and returns the vectors the town stores | headless Chromium with a software graphics adapter: the 130 MB model loaded and embedded four test texts; against the same model run natively (ONNX) the vectors' cosine similarity was 0.95 to 0.98 and the three test memories ranked in the same order against a query. In a padded batch a short text's vector drifted (0.86), so the page embeds one text per pass |
| Vectors fetched in batches change nothing | `tests/test_tab.py`: same state and same stored vectors as a town whose embedding model answers at once |
| Days planned on waking survive resume and replay | `tests/test_waking.py` |
| A ten-resident town opens asleep and wakes one resident at a time | `tests/test_tab.py` and headless Chromium with a stand-in mind: 8 of 10 asleep at opening, thoughts named in the banner, no page errors |

Not checked: an answer from a real language model in this environment. On the software
graphics adapter the 207 MB test model's first answer did not arrive within five minutes, which
says nothing either way about a real chip. None of the five offered models has run here on real
graphics hardware, so there are no speed numbers; nor have Safari, Firefox or phones been
tried, or how long browsers keep a multi-gigabyte model before evicting it. How well a 1B to 8B
model follows the planning prompts is not measured either: an answer that fails its checks is
repaired once and otherwise the resident tries again half a game hour later. The page reports
the model's own speed readings to the console (`__tabTown`), which is where the first real
numbers will come from.

Known limits: a conversation is still written in one step; one town per browser; a town
founded before memory by meaning keeps searching by words until a new town is started; the
publish workflow has not been run.

## Build it, try it, publish it

```bash
cd frontend
npm install
npm run build:tab
```

```bash
python3 -m http.server 8095 --directory dist-tab
```

Then open `http://127.0.0.1:8095`. The folder `frontend/dist-tab` is the whole site (about
33 MB) and can be put on any static host. For GitHub Pages there is a workflow that runs only
when asked: set Settings, Pages, Source to "GitHub Actions" once, then run "Publish the town in
a tab" from the Actions tab or push a tag starting with `site-`.

## What recent research suggests, and what was done with it

A reading of 2024 to 2026 work on cheaper agent simulations and in-browser inference, for this
setup (many short calls, about 550 prompt tokens in and 30 out):

| Finding | Source | Status here |
| --- | --- | --- |
| The browser runtime re-reads the whole prompt on every call; it reuses its cache only when a call continues the previous conversation exactly | WebLLM source ([engine.ts](https://github.com/mlc-ai/web-llm/blob/main/src/engine.ts)); a prefix-cache change is unmerged ([PR 664](https://github.com/mlc-ai/web-llm/pull/664)) | Explains why fewer and shorter prompts matter most. Chaining one resident's mechanical questions into one conversation is the largest remaining speed-up and is not built: it changes the prompts, so it needs its own switch and measurements. |
| A 4B model is reported ahead of Llama 3.1 8B on standard benchmarks | [Qwen3 technical report](https://arxiv.org/html/2505.09388v1) (the authors' own numbers) | Offered as "Bright" at half the 8B's download. No role-play benchmark was found, so this is to be judged in the town. |
| Reusing settled routines cut tokens to 31 to 43 percent of baseline with unchanged human-likeness ratings | [Affordable Generative Agents](https://arxiv.org/html/2402.02053v2) | The same idea as this project's habits and memoized repeats (measured above). Their embedding match with a precondition check would catch more; not built. |
| Compressing social context to a relationship summary cut dialogue prompts from about 2,000 tokens to about 100 | same paper | Not built. This project's relationship records could feed it. |
| Option-level actions (decide once, persist until a cheap termination check) | [Lyfe Agents](https://arxiv.org/html/2310.02172v1) | Partly: a place is chosen once per hour block in the tab town. |
| Static similarity thresholds for a semantic cache carry no error guarantee | [vCache](https://arxiv.org/html/2502.03771v4) | A reason the habit cache keys on exact structured inputs. |
| Fine-tuning a small model on logged decisions can shift social behaviour | [ablation study](https://arxiv.org/html/2605.00197) | Not attempted; the call ledger is the training data if it ever is. |
| The runtime reports prompt and generation speed per answer | WebLLM usage fields | Collected per answer for the first real-device measurement. |

Speculative decoding and model cascades were judged low value here: answers are about 30 tokens
long, and two loaded models double the memory a visitor needs.
