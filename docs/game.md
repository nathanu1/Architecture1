# The town game (an extension)

`ga play` turns the reproduction into a small, cozy town-building game. You are **the town
builder**, a visitor to Smallville. You chat with residents, take on the wishes they come up with,
wrap gifts, collect motifs, and build and decorate the town. The residents are the paper's agents,
unchanged: they remember, retrieve, reflect, plan, react and talk exactly as in the reproduction,
and they meet you only through the channels the paper gives an outside user (talking to them, the
inner voice, changing an object's state) plus one more, the objects you place in the world.

Everything in this document is an **extension** (class X in [`reproduction_spec.md`](reproduction_spec.md),
section 2S). It is off unless a config sets `game.enabled: true`. The look is an original
storybook diorama inspired by life-sim builder games in general; it uses no names, art or assets
from any existing game.

## Running it

```bash
ga play --config configs/town_mock.yaml                 # offline, deterministic mock model (MOCK)
ga play --config configs/town_ollama.yaml               # local open-weight model through Ollama
ga play --resume runs/<id>                              # continue a saved town
ga play --replay runs/<id>                              # watch it again, no model calls
```

The town opens at <http://127.0.0.1:8080>; the research inspector is at `/inspector`. Options:
`--speed slow|normal|fast|max`, `--paused`, `--open` (launch a browser), `--port`, `--host`.
Closing with Ctrl+C saves at the last checkpoint.

**Local models, zero cost.** `configs/town_ollama.yaml` is the three-resident vertical slice
(Isabella, Maria, Klaus) on [Ollama](https://ollama.com/):

```bash
ollama pull llama3.1:8b        # about 4.9 GB; or mistral:7b (about 4.4 GB), llama3:8b (about 4.7 GB)
ollama pull nomic-embed-text   # embeddings
ga doctor --config configs/town_ollama.yaml
ga play --config configs/town_ollama.yaml
```

8 GB of RAM is the minimum for an 8B model and 16 GB is comfortable. On a machine without a
GPU, `llama3.2:3b` (about 2.0 GB) is the practical choice: `ollama pull llama3.2:3b`, then add
`--set providers.llm.model=llama3.2:3b`. The town moves as fast as your machine answers: walking
is instant, each resident decision is one or more model calls. LM Studio and llama.cpp's server
work through the OpenAI-compatible adapter (`providers.llm.kind: openai_compatible`,
`base_url: http://localhost:1234/v1` for LM Studio). Local runs record a cost of zero and need no
API key. When the three-resident slice runs well, `configs/town_n25_ollama.yaml` has all 25
residents (roughly eight times the calls).

**Small models and structured output.** Local servers decode within a grammar built from the
JSON schema they are sent, so besides each task's schema the adapters send a tighter *decoding
schema* that restates the call's own validation rules: the offered choices (places, themes,
reaction options, statement numbers), exact item counts, rating and duration ranges, and clock
times. It removes only answers the validator would reject anyway; checks a grammar cannot
express (durations that must add up, an hourly schedule that must reach midnight) stay with the
validator and its one repair attempt. The decoding schema is stored with each call
(`metadata_json`) and is not part of the replay key, so runs recorded before it still replay.

> **Validation status.** The adapters are tested against a fake HTTP server that follows the
> documented APIs (`tests/fake_ollama.py`), including a full three-resident simulation and its
> call-free replay. They were also run for real, on a CPU-only machine with four cores:
>
> * **Ollama 0.40.2 with Llama 3.2 3B Instruct (Q4_K_M) and `nomic-embed-text`** ran the
>   three-resident town from 07:00 to 18:00 on Monday (with `configs/game/demo_actions.jsonl`
>   and a few more chats and two inner-voice lines). 493 model calls took about 55 minutes of
>   model time (median 3 s per call, 90th percentile 16 s, longest 55 s). 427 of 460 first
>   attempts were valid. Apart from one hourly schedule, fixed by its repair, every invalid
>   answer was an hour decomposition whose durations did not add up: 3 of 33 succeeded, and the
>   other 30 hours stayed single tasks, as designed. The run replays to an identical state with
>   no model calls.
> * What the residents did is plausible but plain. Their day plans, wishes and replies to the
>   player stay in character; Klaus reflected once (three questions, fifteen insights, each
>   citing only statements he was shown). They saw each other 26 times with talking offered and
>   chose to carry on every time, so no resident-to-resident conversation happened, even after
>   an inner-voice nudge. There were slips: Isabella called tomorrow's party "tonight", and Klaus
>   "visited the library" from his dorm desk.
> * Before the decoding schema, the same model failed while seeding memories (its importance
>   ratings were valid in 1 of 12 tries; with it, 12 of 12).
> * The OpenAI-compatible adapter was checked against llama.cpp's `llama-server` (chat with a
>   JSON schema, and embeddings). LM Studio has not been tried.
>
> One run of one small model is a smoke test of the local path, not a result about agent
> behavior.

## What you can do, and what the residents experience

| Action | In the game | In the simulation |
| --- | --- | --- |
| **Chat** | Type to a resident; they answer in their own voice. | One `player_chat` call: the resident's summary, current activity, memories retrieved for what you said, and your recent exchanges. Your line is stored as a statement heard from the builder and their reply as their own statement, both with scored importance, so they can come up later in plans, reflections and conversations. |
| **Ask for a Wish** | The resident tells you something they would like built. Residents also ask on their own once a day (after `game.request_hour`). | One `resident_request` call from the resident's summary, today's plan and memories about their goals. The place must be copied from the resident's own spatial memory and the kind (theme) must fit there; a validator enforces both. Nothing is invented if the call fails. The request line is stored as something the resident said to you. |
| **Build** | Place, move, rotate, paint, duplicate and remove items; templates; undo and redo. | Placed items become real world objects: residents perceive them, can use them, and blocking items change paths. The world is rebuilt from the base map plus the item list, so saves stay exact. |
| **Deliver** | When something of the right kind stands in the right place, the request turns ready; deliver it in person. | A `player_chat` exchange about the new item, stored like any other. |
| **Give a Gift** | Wrap a gift from one motif. | A `player_chat` exchange about the gift. Whether a resident "loves" its theme changes only the game's friendship meter, never the prompt. |
| **Search** | Look through an object for an environmental motif. | No model call; the theme comes from the object and room names. Each object can be searched once per in-game hour. |
| **Collect sparkles** | Pick up the social motif two residents leave behind after a conversation. | No model call; themed by the words of the conversation's summary and lines. |
| **Object state** | Set any object's state ("burning", "empty"), as in the paper. | The paper's intervention: residents perceive the new state and may react. |
| **Whisper** | Speak as a resident's inner voice, as in the paper. | Stored as an inner-voice memory and logged as an intervention. |

**What never reaches a resident.** Town Pulse, friendship hearts, motif counts, affinity scores
and request bookkeeping are game meters for the player. None of them is put into any prompt, and
`tests/test_game.py::test_game_meters_never_reach_a_prompt` checks every prompt of a played run
for them. The research inspector is for the researcher only and never feeds anything back.

## Affinities

Six themes, configured in [`configs/game/affinities.yaml`](../configs/game/affinities.yaml), tie
residents, activities, places, gifts and buildable items together: **Cozy** (warm homes, good
food), **Bloom** (gardens, parks), **Lore** (books, study), **Spark** (parties, music), **Craft**
(making things) and **Kin** (neighbors, community). Scoring is deterministic whole-word keyword
matching (no model calls):

* a resident loves the top two themes of their identity text (innate, learned and currently
  fields), unless `configs/game/residents.yaml` overrides them;
* a place scores its building name once, its room twice and its object three times, plus the
  themes of items already placed there;
* while building, the panel shows which residents love an item's theme, whether its paint
  matches, how the room feels and whether it fulfils an open request.

## Motifs, gifts and the catalog

* **Motifs** ([`motifs.yaml`](../configs/game/motifs.yaml)): three per theme, two environmental
  (found by searching objects) and one social (left behind by residents' conversations). They pay
  for items and gifts. A new town starts with `game.starting_motifs` (2) motifs of each theme.
* **Gifts**: six, one per theme, each wrapped from one motif.
* **Catalog** ([`catalog.yaml`](../configs/game/catalog.yaml)): 32 items with a theme, footprint,
  placement (indoor, outdoor or anywhere), cost and the Town Pulse level that unlocks it; 9
  paints; 5 templates. Saved templates are added to the list.

## Build and decorate

Every change is validated twice: live while you hover (a green or red ghost) and again on the
engine thread when the batch is applied, against the state at that step. A batch is all or
nothing, removals refund their cost, and every problem is named:

* unlocks at a later Town Pulse level; not enough motifs;
* goes off the edge of the map; a wall or obstacle is in the way; must sit inside a single room
  or garden; needs to be inside a room, garden or park, not on the street;
* belongs indoors, or outdoors in a garden or park;
* overlaps something already there; would cover too much of a garden's ground cover;
* someone is standing there, or walking through; someone is using the object;
* would cut off walkable tiles from the rest of town (connected-component check).

The Town Square (`configs/game/town.yaml`) turns an open stretch of street into a named place, so
there is room to build outdoors.

## Town Pulse

Five levels ([`pulse.yaml`](../configs/game/pulse.yaml)): Sleepy Hamlet (0 points), Waking
Village (40), Friendly Town (120), Lively Town (260) and Storybook Town (480). Points come from
what you do (chats, gifts, motifs, placing items, fulfilled requests) and from the residents' own
conversations. Levels unlock items and templates.

## Determinism: save, resume, replay

Player actions are appended (and fsynced) to `actions.jsonl` in the run directory and applied by
the engine at the next step boundary, never mid-step. Model calls made for them go through the
same ledger as every other call. As a result:

* `ga play --replay runs/<id>` and `ga replay` reproduce a played town exactly with **zero** model
  calls (`test_a_played_run_replays_exactly_without_any_model_call`);
* a crash resumes from the last checkpoint and re-applies each logged action once
  (`test_resume_after_a_crash_reapplies_player_actions_once`);
* `ga run --config ... --actions FILE` plays a scripted session headlessly
  (`configs/game/demo_actions.jsonl`).

A failed model call stops the town at its last checkpoint with the error shown; Retry continues.

## Architecture

* `src/generative_agents/game/`: `content.py` (config models), `affinity.py`, `world_edit.py`
  (zones, placement validation, world rebuild), `store.py` (game tables in the run's SQLite),
  `actions.py` (the action log), `layer.py` (hooks into the engine's step, checkpoint and
  rollback), `session.py` (the live engine thread, speed, pause, retry and the published
  snapshot), `api.py` (HTTP).
* HTTP: `GET /api/game/info|map|poll`, `POST /api/game/action|validate-build|control`,
  `GET /api/game/resident/{id}`, `GET /api/game/object?address=`; the read-only research API is
  mounted at `/research`.
* `frontend/`: React, Tailwind, Motion, Phosphor icons and a Three.js toon-shaded diorama with a
  three-quarter orthographic camera. `npm run build` writes the bundle to
  `src/generative_agents/game/web/`, which is committed so `ga play` needs no Node.js. For
  development: `cd frontend && npm ci && npm run dev` (proxies the API to `ga play` on port 8080).
* Keyboard: N notebook, L Look Around (a list of the sparkles, placed items and objects near the
  middle of the view, so everything clickable in the town is also reachable without a pointer),
  B build, Q and E turn, + and - zoom, WASD or arrows pan, Space pauses, Esc closes. In build
  mode, once an item or template is chosen, the arrows move the placement cursor and P (or Enter)
  places it; R rotates, D duplicates, Delete removes, Ctrl+Z and Ctrl+Shift+Z (⌘ on a Mac) undo
  and redo. The notebook page and the inspector's view, filters and open call live in the URL.

## Sharing a recorded town

`ga export-demo --run-dir DIR --out SITE` replays a run (no model calls) and writes what the
interface would have polled into `SITE/demo/`: one frame per step (with string tables, so a
three-resident morning is about 0.4 MB), the game state whenever it changes, every event with its
step, and the research inspector's data at the end of the run. `npm run build:demo` builds the
same interface in a demo mode that plays those files: play, pause, three speeds, a timeline to
drag, and chips for the moments worth seeing (chats, gifts, builds, wishes, resident
conversations). Everything is view-only; chatting, gifts and building need a live town. The demo
page uses hash links (`#inspector`) so it works inside frames that cannot change their path. It
names the model that wrote the residents' words (or says it was the mock) and claims only what
the recording contains; it opens fifteen game minutes before the player's first action and waits
until the welcome card is dismissed.

## Research inspector

`/inspector` shows, per resident: the memory stream with kinds, origins and importance;
retrievals with the recency, importance and relevance of each candidate; plans at every level;
reflections with their evidence trees; information diffusion of the two seeded topics with every
transmission; and the provenance of every model call (prompt, raw output, validation, repairs,
tokens, model and digest). Mock runs and mock hash embeddings are flagged on the page: they are
test fixtures, not research results.
