"""The town in a browser tab (game/tab.py): driven pass by pass with no threads, pausing for the
model's answers and repeating the unanswered step. Run here under CPython; tests/tab_node.mjs
runs the same class inside Pyodide."""

from __future__ import annotations

import json

import pytest

from generative_agents.game.tab import SCRIPTED, TabTown
from generative_agents.providers.deferred import Deferred, DeferredLLM
from generative_agents.providers.mock import MockLLM
from generative_agents.viewer.routes import NotFound, dispatch

TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")
HOUR = ["scenario.end=2023-02-13T07:40:00"]


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
        "configs/town_tab.yaml", overrides=[*HOUR, "providers.llm.kind=mock", "providers.llm.model=mock-llm-v1", "output.checkpoint_every_steps=1"]
    )
    server = Simulation(cfg, tmp_path / "server")
    assert server.run() == "completed"
    assert town.sim.db.content_hash(TABLES) == server.db.content_hash(TABLES)


def test_pausing_for_the_model_and_repeating_the_step_gives_exactly_the_blocking_run(tmp_path):
    """The heart of the tab: answers arrive later, one at a time, and nothing differs."""

    waiting = TabTown(tmp_path / "waiting", mind="tiny-model", overrides=HOUR, speed="max")
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
    first = TabTown(tmp_path / "t", mind=SCRIPTED, overrides=["scenario.end=2023-02-13T07:10:00"], speed="max")
    drive(first)
    step = first.sim.clock.step
    first.close()
    later = TabTown(tmp_path / "t", mind="tiny-model", overrides=["scenario.end=2023-02-13T07:20:00"], speed="max")
    assert later.resumed and later.info()["resumed"] and isinstance(later.model, DeferredLLM)
    drive(later, answer=lambda need: later.deliver(need["key"], later.scripted_answer(need["key"])))
    assert later.sim.clock.step > step and later.session.finished
    later.close()


def test_a_model_that_fails_or_runs_out_of_room_stops_the_town_visibly(tmp_path):
    town = TabTown(tmp_path / "t", mind="tiny-model", overrides=HOUR, speed="max")
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
    cut = TabTown(tmp_path / "cut", mind="tiny-model", overrides=HOUR, speed="max")
    short = cut.tick()["need"]
    cut.deliver(short["key"], '{"rating": 3', finish="length")
    assert cut.tick()["status"] == "error" and "length limit" in cut.session.error
    assert [r["status"] for r in cut.sim.rt.ledger.rows(limit=1)] == ["truncated"]
    model = DeferredLLM("m")
    with pytest.raises(ValueError, match="scripted"):
        TabTown(tmp_path / "s", mind=SCRIPTED, overrides=HOUR).deliver("k", "{}")
    assert issubclass(Deferred, BaseException) and not issubclass(Deferred, Exception) and model.describe()["local"]
