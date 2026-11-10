"""The town in a browser tab (game/tab.py): driven pass by pass with no threads, pausing for the
model's answers and repeating the unanswered step. Run here under CPython; tests/tab_node.mjs
runs the same class inside Pyodide."""

from __future__ import annotations

import base64
import hashlib
import json

import numpy as np
import pytest

from generative_agents.game.tab import EMBED_DIMS, EMBED_MODEL, EMBED_QUERY_PREFIX, SCRIPTED, TabTown
from generative_agents.providers.deferred import Deferred, DeferredEmbedding, DeferredLLM
from generative_agents.providers.mock import MockLLM
from generative_agents.viewer.routes import NotFound, dispatch

TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")
HOUR = ["scenario.end=2023-02-13T07:40:00"]  # the town opens when its first resident wakes, about six


def meaning(texts: list[str]) -> np.ndarray:
    """A stand-in for the page's embedding model: one fixed unit vector per text, nothing like
    the lexical stand-ins the town uses while it waits (so a leaked stand-in changes the town)."""

    rows = [np.random.default_rng(int(hashlib.sha256(t.encode()).hexdigest()[:16], 16)).standard_normal(EMBED_DIMS) for t in texts]
    arr = np.asarray(rows, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=1, keepdims=True)


def page(town: TabTown, asked: list[str] | None = None):
    """The page's side: the model answers with the offline fixture, the embedding model with ``meaning``."""

    def answer(need):
        if asked is not None:
            asked.append(need["task"])
        if need.get("kind") == "embed":
            town.deliver_vectors(need["key"], base64.b64encode(meaning(need["texts"]).astype("<f4").tobytes()).decode(), len(need["texts"]))
        else:
            town.deliver(need["key"], town.scripted_answer(need["key"]))

    return answer


def drive(town: TabTown, *, answer=None, passes=100000) -> dict[str, int]:
    """Tick until the scenario ends; ``answer(need)`` plays the page's model."""

    seen = {"needs": 0, "passes": 0}
    for _ in range(passes):
        out = town.tick()
        seen["passes"] += 1
        if "need" in out:
            seen["needs"] += 1
            answer(out["need"])
        elif town.session.finished:
            break
    return seen


def test_a_scripted_town_in_a_tab_is_the_same_town_a_server_would_run(tmp_path):
    town = TabTown(tmp_path / "tab", mind=SCRIPTED, overrides=HOUR, speed="max")
    assert drive(town)["needs"] == 0 and town.session.finished and town.model is None
    from generative_agents.config import load_config
    from generative_agents.simulation.engine import Simulation

    cfg = load_config(
        "configs/town_tab.yaml",
        overrides=[
            *HOUR,
            f"scenario.start={town.cfg.scenario.start.isoformat()}",
            "providers.llm.kind=mock",
            "providers.llm.model=mock-llm-v1",
            "output.checkpoint_every_steps=1",
        ],
    )
    assert 5 <= town.cfg.scenario.start.hour <= 6  # dawn: the earliest riser of the three wakes around six
    server = Simulation(cfg, tmp_path / "server")
    assert server.run() == "completed"
    assert town.sim.db.content_hash(TABLES) == server.db.content_hash(TABLES)


def test_pausing_for_the_model_and_repeating_the_step_gives_exactly_the_blocking_run(tmp_path):
    """The heart of the tab: answers arrive later, one at a time, and nothing differs."""

    waiting = TabTown(tmp_path / "waiting", mind="tiny-model", depth="full", memory="words", overrides=HOUR, speed="max")
    assert isinstance(waiting.model, DeferredLLM) and waiting.info()["mind"] == "tiny-model"
    asked: list[str] = []

    def answer(need):
        assert set(need) >= {"key", "task", "system", "prompt", "schema", "max_tokens", "model"} and need["model"] == "tiny-model"
        asked.append(need["task"])
        waiting.deliver(need["key"], waiting.scripted_answer(need["key"]))

    seen = drive(waiting, answer=answer)
    usage = waiting.sim.rt.budget.usage
    assert seen["needs"] == usage.calls == len(asked) > 30 and waiting.repeats == seen["needs"]
    assert {"day_plan", "importance", "choose_location"} <= set(asked)

    # the same town with a model that answers on the spot (same model name, so the same requests)
    from generative_agents.game.session import GameSession

    cfg = waiting.cfg.model_copy(deep=True)
    blocking = GameSession(cfg, tmp_path / "blocking", provider=_Blocking(MockLLM(seed=cfg.run.seed)), speed="max")
    while not blocking.finished:
        blocking.iterate()
    assert blocking.sim.rt.budget.usage.calls == usage.calls
    assert waiting.sim.db.content_hash(TABLES) == blocking.sim.db.content_hash(TABLES)
    # every question is in the ledger once, with its answer, like any other call
    rows = waiting.sim.rt.ledger.rows()
    assert len(rows) == usage.calls and all(r["provider"] == "browser" and r["status"] == "ok" for r in rows)


class _Blocking:
    """The offline fixture under the browser provider's name, answering at once."""

    name = "browser"

    def __init__(self, inner):
        self.inner = inner

    def describe(self):
        return {"provider": "browser"}

    def complete(self, request):
        return self.inner.complete(request)


def test_the_page_talks_to_the_town_through_one_door_and_gets_http_like_answers(tmp_path):
    town = TabTown(tmp_path / "t", mind=SCRIPTED, overrides=HOUR, speed="max", paused=True)
    for _ in range(3):
        town.tick()

    def call(method, *args):
        return json.loads(town.call(method, json.dumps(list(args))))

    info = call("info")["ok"]
    assert info["tab"] and info["mind"] == SCRIPTED and len(info["residents"]) == 3 and "live" in info["speeds"]
    assert call("map")["ok"]["width"] == 140
    poll = call("poll", -2, 0)["ok"]
    assert poll["paused"] and poll["clock"] and poll["frames"]
    who = info["residents"][0]["id"]
    assert call("resident", who)["ok"]["id"] == who
    assert call("resident", "nobody")["error"]["status"] == 404
    assert call("control", "speed", "warp")["error"]["status"] == 400
    assert call("control", "resume")["ok"]["paused"] is False
    assert call("_roll_back")["error"]["status"] == 404 and call("close")["error"]["status"] == 404
    sent = call("action", "chat", {"agent": who, "text": "Good morning!"})["ok"]
    assert sent["seq"] == 1
    for _ in range(40):
        town.tick()
    assert any(e["kind"] == "chat" for e in call("poll", -2, 0)["ok"]["feed"])
    # the research inspector's paths, without a web server
    assert call("research", "run")["ok"]["agents"]
    memories = call("research", f"agent/{who}/memories?limit=5")["ok"]
    assert 0 < len(memories) <= 5
    assert call("research", "behavior")["ok"] and call("research", "network?points=4")["ok"]
    assert call("research", "no/such/path")["error"]["status"] == 404
    assert call("stats")["ok"]["calls"] > 0
    with pytest.raises(NotFound):
        dispatch(town._data, "trace/does-not-exist")


def test_a_town_in_a_tab_continues_after_the_tab_is_closed_and_can_change_its_mind(tmp_path):
    first = TabTown(tmp_path / "t", mind=SCRIPTED, overrides=["scenario.end=2023-02-13T06:40:00"], speed="max")
    drive(first)
    step = first.sim.clock.step
    first.close()
    later = TabTown(tmp_path / "t", mind="tiny-model", depth="full", overrides=["scenario.end=2023-02-13T07:20:00"], speed="max")
    assert later.resumed and later.info()["resumed"] and isinstance(later.model, DeferredLLM)
    drive(later, answer=lambda need: later.deliver(need["key"], later.scripted_answer(need["key"])))
    assert later.sim.clock.step > step and later.session.finished
    later.close()


def test_a_model_that_fails_or_runs_out_of_room_stops_the_town_visibly(tmp_path):
    town = TabTown(tmp_path / "t", mind="tiny-model", depth="full", memory="words", overrides=HOUR, speed="max")
    need = town.tick()["need"]
    assert town.poll()["thinking"]  # the interface shows who is waiting for an answer
    town.fail(need["key"], "the GPU was lost")
    assert not town.poll()["thinking"]
    out = [town.tick() for _ in range(3)]
    assert town.session.error and "the GPU was lost" in town.session.error and "need" not in out[-1]
    assert json.loads(town.call("control", '["retry"]'))["ok"]["status"] == "starting"
    again = next(o["need"] for o in (town.tick() for _ in range(5)) if "need" in o)
    assert again["key"] == need["key"]  # the same question is asked again, not answered with the old failure
    drive(town, answer=lambda n: town.deliver(n["key"], town.scripted_answer(n["key"])))
    assert town.session.finished and town.session.error is None
    # an answer cut off at its length limit is a failed task, recorded as such, and the page hears about it
    cut = TabTown(tmp_path / "cut", mind="tiny-model", depth="full", memory="words", overrides=HOUR, speed="max")
    short = cut.tick()["need"]
    cut.deliver(short["key"], '{"rating": 3', finish="length")
    assert cut.tick()["status"] == "error" and "length limit" in cut.session.error
    assert [r["status"] for r in cut.sim.rt.ledger.rows(limit=1)] == ["truncated"]
    model = DeferredLLM("m")
    with pytest.raises(ValueError, match="scripted"):
        TabTown(tmp_path / "s", mind=SCRIPTED, overrides=HOUR).deliver("k", "{}")
    assert issubclass(Deferred, BaseException) and not issubclass(Deferred, Exception) and model.describe()["local"]


def test_with_depth_words_the_model_writes_the_words_and_routine_comes_from_the_script(tmp_path):
    """The fastest setting: plans, places and importance are answered at once and the model is
    asked only for what a visitor reads."""

    town = TabTown(tmp_path / "t", mind="tiny-model", depth="words", residents=10, overrides=["scenario.end=2023-02-13T09:00:00"], speed="max")
    assert len(town.info()["residents"]) == 10
    asked: list[str] = []
    drive(town, answer=page(town, asked))
    asked = [t for t in asked if t != "embed"]
    rows = town.sim.rt.ledger.rows()
    by_provider = {p: {r["task"] for r in rows if r["provider"] == p} for p in {r["provider"] for r in rows}}
    assert by_provider["routine:mock"] >= {"day_plan", "choose_location", "importance"}
    assert not (set(asked) & set(by_provider["routine:mock"]))  # nothing routine reached the model
    assert set(asked) == by_provider.get("browser", set()) and len(asked) < len(rows) / 4
    fidelity = {r["setting"]: r["class"] for r in town.cfg.fidelity_table()}
    assert fidelity["providers.llm.pools"] == "E"
    with pytest.raises(ValueError, match="depth"):
        TabTown(tmp_path / "x", mind="tiny-model", depth="deep")


def test_by_default_the_model_plans_every_day_and_the_town_wakes_one_resident_at_a_time(tmp_path):
    """Nothing a resident does is scripted, and the town still opens at once: it starts when its
    earliest riser wakes, everyone else is in bed, and each plans their day on waking."""

    town = TabTown(tmp_path / "t", mind="tiny-model", residents=10, overrides=["scenario.end=2023-02-13T07:30:00"], speed="max")
    info = town.info()
    assert info["memory"] == "meaning" and info["embed_model"] == EMBED_MODEL and town.cfg.scenario.start.hour in (4, 5)
    asked: list[str] = []
    answer = page(town, asked)
    first_step: list[str] = []
    planned_at: dict[str, int] = {}
    for _ in range(100000):
        out = town.tick()
        if "need" in out:
            if out["need"]["task"] == "day_plan":
                planned_at[out["need"]["agent_id"]] = town.sim.clock.step
            answer(out["need"])
        elif town.session.finished:
            break
        if town.sim.clock.step == 1 and not first_step:
            first_step = [t for t in asked if t != "embed"]
            sleeping = [v.sleeping for v in town.sim.views().values()]
            assert sum(sleeping) >= 8  # the town opens on a sleeping street
    rows = town.sim.rt.ledger.rows()
    assert {r["provider"] for r in rows} == {"browser"}  # no scripted pool: every answer is the model's
    model_tasks = {t for t in asked if t != "embed"}
    assert {"day_plan", "hourly_schedule", "decompose", "choose_location", "action_grounding"} <= model_tasks
    assert not ({"importance", "importance_batch"} & model_tasks)  # read from meaning, never asked
    assert len(first_step) <= 12  # the first step waits for one or two risers, not for ten plans
    assert len(planned_at) >= 6 and len(set(planned_at.values())) >= 5  # plans arrive through the morning
    # a resident who has lived nothing is not asked to summarise it
    assert "summary_aspect" not in first_step
    # vectors are fetched in batches: far fewer round trips than texts
    stats = town.stats()
    assert stats["embedded"] > 200 and stats["embed_rounds"] < stats["embedded"] / 3
    fidelity = {r["setting"]: r["class"] for r in town.cfg.fidelity_table()}
    assert fidelity["planning.at_waking"] == fidelity["importance.strategy"] == fidelity["summary.min_lived"] == "X"
    # importance came out as ratings in range, and not all alike
    ratings = [r["importance"] for r in town.sim.db.query("SELECT importance FROM memories WHERE origin != 'seed'")]
    assert ratings and all(1 <= r <= 10 for r in ratings)


def test_a_conversation_is_shown_line_by_line_while_it_is_being_written(tmp_path):
    """The clock stands still while two residents talk; the page is told the line just said,
    so it can show it over the speaker's head while the other finds an answer."""

    town = TabTown(tmp_path / "t", mind="tiny-model", residents=10, overrides=["scenario.end=2023-02-13T12:00:00"], speed="max")
    answer = page(town)
    heard = None
    turns = 0
    for _ in range(200000):
        out = town.tick()
        if "need" in out:
            need = out["need"]
            if need["task"] == "dialogue_turn":
                turns += 1
                thought = town.poll()["thinking"][need["agent_id"]]
                assert thought["task"] == "dialogue_turn"
                if "heard" in thought:
                    heard = (thought["heard"], need)
                    break
            answer(need)
        elif town.session.finished:
            break
    assert heard is not None and turns >= 2  # the opening line has nothing before it
    line, need = heard
    assert line["from"] != need["agent_id"] and line["from"] in {r["id"] for r in town.info()["residents"]}
    assert line["text"] and line["text"] in need["prompt"]
    answer(need)
    assert not town.poll()["thinking"]


class _Meaning:
    """``meaning`` as an embedding model the town can call directly (what a server would have)."""

    is_fixture = False
    model_id, dims, revision = EMBED_MODEL, EMBED_DIMS, None

    def embed(self, texts):
        arr = meaning([t[: DeferredEmbedding.MAX_CHARS] for t in texts])
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12)  # as the town normalises what the page sends

    def describe(self):
        return {"kind": "browser", "model": self.model_id, "dims": self.dims}


def test_memory_by_meaning_waits_for_its_vectors_in_batches_and_changes_nothing(tmp_path):
    """Vectors come from the page, a batch per pass; the passes that ran on stand-ins are undone
    in full, so the town is exactly the one whose embedding model answers on the spot."""

    waiting = TabTown(tmp_path / "waiting", mind="tiny-model", overrides=HOUR, speed="max")
    assert isinstance(waiting.embedder, DeferredEmbedding)
    kinds: list[str] = []
    seen = drive(waiting, answer=page(waiting, kinds))
    assert waiting.session.finished and waiting.session.error is None and "embed" in kinds
    assert not waiting.embedder.missing and waiting.repeats == seen["needs"]
    # a query carries the embedding model's instruction for queries; a stored memory does not
    service = waiting.sim.rt.embeddings
    service.embed_query("what does Klaus care about?")
    assert list(waiting.embedder.missing) == [EMBED_QUERY_PREFIX + "what does Klaus care about?"] and service.provisional
    waiting.embedder.missing.clear()
    waiting.sim.db.rollback()

    from generative_agents.game.session import GameSession

    cfg = waiting.cfg.model_copy(deep=True)
    blocking = GameSession(cfg, tmp_path / "blocking", provider=_Blocking(MockLLM(seed=cfg.run.seed)), embedding_provider=_Meaning(), speed="max")
    while not blocking.finished:
        blocking.iterate()
    assert blocking.sim.rt.budget.usage.calls == waiting.sim.rt.budget.usage.calls
    assert waiting.sim.db.content_hash((*TABLES, "embeddings")) == blocking.sim.db.content_hash((*TABLES, "embeddings"))
    # a town founded this way keeps its embedding model when it is reopened, whatever the mind
    waiting.close()
    again = TabTown(tmp_path / "waiting", mind=SCRIPTED, overrides=["scenario.end=2023-02-13T07:50:00"], speed="max")
    assert again.resumed and again.info()["memory"] == "meaning" and again.model is None
    drive(again, answer=page(again))
    assert again.session.finished and again.session.error is None
    # a failing embedding model stops the town visibly, and Retry asks again
    broken = TabTown(tmp_path / "broken", mind="tiny-model", overrides=HOUR, speed="max")
    need = broken.tick()["need"]
    assert need["kind"] == "embed" and need["texts"]
    broken.fail(need["key"], "the GPU was lost")
    assert broken.session.error and "memory model" in broken.session.error
    with pytest.raises(ValueError, match="by words"):
        TabTown(tmp_path / "w", mind="tiny-model", memory="words", overrides=HOUR).deliver_vectors("k", "", 1)


def test_talking_to_a_resident_twice_asks_twice_and_shows_each_reply_once(tmp_path):
    """The player's words are their own unit of work: answered ahead of the step, shown once
    however often the step behind them is repeated, and never answered from an earlier reply."""

    town = TabTown(tmp_path / "t", mind="tiny-model", overrides=HOUR, speed="max")
    answer = page(town)
    while not town.session._ready:
        out = town.tick()
        if "need" in out:
            answer(out["need"])
    who = town.info()["residents"][0]["id"]
    chat_questions = 0
    for nth in (1, 2):
        town.action("chat", {"agent": who, "text": "how are you doing"})
        for _ in range(400):
            out = town.tick()
            if "need" in out:
                chat_questions += out["need"]["task"] == "player_chat"
                answer(out["need"])
            if sum(e["kind"] == "chat" for e in town.poll()["feed"]) >= nth:
                break
    feed = [e for e in town.poll()["feed"] if e["kind"] == "chat"]
    assert len(feed) == 2 and chat_questions == 2  # two replies shown, both asked of the model
    assert len(town.sim.rt.ledger.rows(task="player_chat")) == 2
    assert sum(e["kind"] == "welcome" for e in town.poll()["feed"]) == 1  # nothing is shown twice
    # the second question carried the first exchange, so the resident is not starting over
    second = town.sim.rt.ledger.rows(task="player_chat")[1]
    assert second["prompt"].count("how are you doing") >= 2
