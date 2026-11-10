"""Parallel deciding (simulation/parallel.py): residents think in rounds, a round's model tasks
are answered together, and the town never depends on how long a reply took."""

from __future__ import annotations

import json
import threading
import time

import pytest

from generative_agents.providers.base import BudgetExceeded
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.mock import MockLLM
from generative_agents.simulation.engine import Simulation
from generative_agents.simulation.parallel import RoundScheduler
from helpers import CountingLLM, sim_config

FIVE = ["isabella_rodriguez", "klaus_mueller", "maria_lopez", "sam_moore", "wolfgang_schulz"]
TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")
MORNING = dict(start="2023-02-13T06:00:00", end="2023-02-13T07:30:00")


# ------------------------------------------------------------------------------- the scheduler
def test_turns_think_one_at_a_time_in_order_and_a_rounds_tasks_are_asked_together():
    sched = RoundScheduler(4)
    log: list[str] = []

    def turn(name: str, tasks: int):
        def run():
            for i in range(tasks):
                log.append(f"{name} thinks")
                answer = sched.defer(lambda n=name, i=i: f"{n}{i}")
                log.append(f"{name} got {answer}")
            log.append(f"{name} done")

        return name, run

    sched.run([turn("a", 2), turn("b", 0), turn("c", 1)])
    assert log == [
        "a thinks",  # round 1: everyone runs to its first task or to the end, in order
        "b done",
        "c thinks",
        "a got a0",  # round 2: answers are delivered in the same order
        "a thinks",
        "c got c0",
        "c done",
        "a got a1",  # round 3
        "a done",
    ]
    assert sched.stats == {"steps": 1, "rounds": 2, "tasks": 3, "widest": 2, "model_calls": 0, "model_waits": 0}
    assert not sched.in_turn()
    sched.close()


def test_a_tasks_error_reaches_its_own_turn_and_a_failed_turn_abandons_the_step():
    sched = RoundScheduler(2)
    seen: list[str] = []

    def careful():
        try:
            sched.defer(lambda: (_ for _ in ()).throw(ValueError("bad reply")))
        except ValueError as exc:
            seen.append(f"handled {exc}")

    sched.run([("a", careful)])
    assert seen == ["handled bad reply"]

    def stops():
        sched.defer(lambda: None)
        raise BudgetExceeded("calls", 1, 1)

    def waits():
        sched.defer(lambda: None)
        sched.defer(lambda: None)
        seen.append("never: the step was abandoned while this turn was paused")

    with pytest.raises(BudgetExceeded):
        sched.run([("a", stops), ("b", waits), ("c", lambda: None)])
    assert len(seen) == 1
    sched.run([("a", lambda: seen.append("the scheduler is usable after a failed step"))])
    assert seen[-1].startswith("the scheduler is usable")
    sched.close()


# ------------------------------------------------------------------------------------ the town
def town(tmp_path, name, *, extra=(), provider=None, replay=None, **when):
    cfg = sim_config(FIVE, **(when or MORNING), extra=extra)
    return Simulation(
        cfg,
        tmp_path / name,
        provider=None if replay else provider or CountingLLM(MockLLM(seed=5)),
        embedding_provider=MockHashEmbedding(128),
        replay_from=replay,
    )


def test_the_town_is_the_same_for_any_number_of_parallel_calls_and_replays_exactly(tmp_path):
    two = town(tmp_path, "two", extra=("engine.parallel_calls=2",))
    eight = town(tmp_path, "eight", extra=("engine.parallel_calls=8",))
    again = town(tmp_path, "again", extra=("engine.parallel_calls=8",))
    assert two.run() == eight.run() == again.run() == "completed"
    assert two.db.content_hash(TABLES) == eight.db.content_hash(TABLES) == again.db.content_hash(TABLES)
    stats = eight.scheduler.stats
    assert stats["widest"] >= 3 and stats["tasks"] > stats["rounds"]  # several residents were asked together
    manifest = json.loads((tmp_path / "eight" / "manifest.json").read_text())
    assert manifest["parallel"]["calls"] == 8 and manifest["parallel"]["rounds"] == stats["rounds"]
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["engine.parallel_calls"] == "X"
    replay = town(tmp_path, "replay", extra=("engine.parallel_calls=8",), replay=tmp_path / "eight")
    assert replay.run() != "failed" and replay.rt.budget.usage.calls == 0
    assert replay.db.content_hash(TABLES) == eight.db.content_hash(TABLES)


def test_parallel_deciding_is_off_by_default_and_leaves_the_sequential_engine_untouched(tmp_path):
    plain = town(tmp_path, "plain")
    assert plain.scheduler is None and plain.rt.gateway.scheduler is None
    assert plain.run() == "completed"
    manifest = json.loads((tmp_path / "plain" / "manifest.json").read_text())
    assert manifest["parallel"] is None
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["engine.parallel_calls"] == "P"


class SlowLLM:
    """A model server that takes a moment per request and counts how many it serves at once."""

    name = "slow"

    def __init__(self, inner, delay=0.01):
        self.inner, self.delay = inner, delay
        self.lock = threading.Lock()
        self.in_flight = self.most = self.calls = 0

    def describe(self):
        return self.inner.describe()

    def complete(self, request):
        with self.lock:
            self.in_flight += 1
            self.calls += 1
            self.most = max(self.most, self.in_flight)
        try:
            time.sleep(self.delay)
            return self.inner.complete(request)
        finally:
            with self.lock:
                self.in_flight -= 1


def test_a_server_that_answers_several_requests_at_once_is_actually_used_that_way(tmp_path):
    hour = dict(start="2023-02-13T06:00:00", end="2023-02-13T06:20:00")
    one = SlowLLM(MockLLM(seed=5))
    sequential = town(tmp_path, "seq", provider=one, **hour)
    started = time.monotonic()
    assert sequential.run() == "completed"
    t_seq = time.monotonic() - started
    many = SlowLLM(MockLLM(seed=5))
    parallel = town(tmp_path, "par", provider=many, extra=("engine.parallel_calls=8",), **hour)
    started = time.monotonic()
    assert parallel.run() == "completed"
    t_par = time.monotonic() - started
    assert one.most == 1 and many.most >= 3  # the sequential engine never overlaps calls; the rounds do
    assert many.calls == one.calls  # the same work, asked differently
    stats = parallel.scheduler.stats
    # waits on the model, by construction: calls made in residents' turns (conversations are a
    # turn-by-turn chain and stay outside the rounds) against the rounds that waited for them
    assert 0 < stats["model_calls"] <= many.calls and stats["model_waits"] < 0.6 * stats["model_calls"]
    assert t_par < t_seq  # and on the clock


def test_a_stopped_parallel_town_resumes_into_exactly_the_uninterrupted_one(tmp_path):
    whole = town(tmp_path, "whole", extra=("engine.parallel_calls=4",))
    assert whole.run() == "completed"
    total = whole.rt.budget.usage.calls
    cut = town(tmp_path, "cut", extra=("engine.parallel_calls=4", f"budget.max_calls={total // 2}"))
    assert cut.run() == "budget_exhausted"
    cut.close()
    resumed = town(tmp_path, "cut", extra=("engine.parallel_calls=4", "budget.max_calls=100000"))
    assert resumed.run() == "completed"
    assert resumed.db.content_hash(TABLES) == whole.db.content_hash(TABLES)
    assert len(resumed.rt.provider.calls) < total  # calls recorded before the stop were not made again
