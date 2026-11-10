"""Switches that keep a town human-paced when one small model does all the thinking
(configs/town_tab.yaml): days planned on waking, summaries only of something lived, and
importance read from meaning. Each is off by default and class X when on."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from generative_agents.cognition.importance import EVERYDAY, MOMENTOUS, ImportanceScorer, MeaningImportance
from generative_agents.cognition.planning import is_sleep, usual_wake, waking_at
from generative_agents.providers.deferred import DeferredEmbedding
from generative_agents.providers.embeddings import EmbeddingService
from generative_agents.providers.mock import MockLLM
from generative_agents.schemas import MemoryKind, MemoryOrigin, PlanLevel
from generative_agents.simulation.engine import Simulation
from helpers import ISABELLA, KLAUS, CountingLLM, make_sim, make_stack, sim_config

TRIO = ["isabella_rodriguez", "klaus_mueller", "maria_lopez"]
TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "embeddings")
WAKING = ("planning.at_waking=true",)


# ---------------------------------------------------------------------------------- waking hours
@pytest.mark.parametrize(
    "lifestyle, minute",
    [
        ("Isabella Rodriguez goes to bed around 11pm, awakes up around 6am.", 360),
        ("Eddy Lin goes to bed around 11pm, awakes up around 7amam, eats dinner around 5pm.", 420),
        ("She wakes up at 7:30 am and runs.", 450),
        ("He gets up around 12pm after a night shift.", 720),
        ("Wakes up around 12am.", 0),
        ("Rises up by 5 and milks the cows.", 300),
        ("Goes to bed around 11pm and eats dinner around 6pm.", None),
        ("Wakes up around 25am.", None),
        ("", None),
    ],
)
def test_the_usual_waking_hour_is_read_from_the_lifestyle(lifestyle, minute):
    assert usual_wake(lifestyle) == minute


def test_a_person_wakes_around_their_hour_the_same_minute_every_time_it_is_asked():
    day = date(2023, 2, 13)
    first = waking_at(ISABELLA, day)
    assert first == waking_at(ISABELLA, day)
    six = datetime(2023, 2, 13, 6, 0)
    week = [waking_at(ISABELLA, day + timedelta(days=k)) - timedelta(days=k) for k in range(14)]
    assert all(six - timedelta(minutes=10) <= t <= six + timedelta(minutes=20) for t in week) and len(set(week)) > 3
    assert waking_at(ISABELLA.model_copy(update={"lifestyle": "keeps no schedule"}), day) is None


def test_with_at_waking_a_new_town_sleeps_in_its_own_beds_and_each_day_is_planned_on_waking(tmp_path):
    llm = CountingLLM(MockLLM(seed=5))
    sim = make_sim(tmp_path, TRIO, provider=llm, start="2023-02-13T00:00:00", end="2023-02-13T11:00:00", extra=WAKING)
    sim.run(max_steps=1)
    # nobody is asked where to sleep or how; only the first memories are rated, as always
    assert {c.task for c in llm.calls} <= {"importance", "importance_batch"}
    for aid, ident in sim.identities.items():
        act = sim.svc.states.get(aid).action
        assert is_sleep(act.description) and act.address == f"{ident.living_area}:bed" and sim.views()[aid].sleeping
        nap = sim.plans.at(aid, PlanLevel.TASK, sim.clock.now)
        assert nap.source == "asleep" and nap.end == waking_at(ident, date(2023, 2, 13))
    sim.run()
    planned = {r["agent_id"]: datetime.fromisoformat(r["sim_time"]) for r in sim.rt.ledger.rows(task="day_plan")}
    assert set(planned) == set(TRIO)
    for aid, ident in sim.identities.items():
        wake = waking_at(ident, date(2023, 2, 13))
        assert wake <= planned[aid] < wake + timedelta(minutes=1)  # the first step at or after waking
        assert sim.planner.has_day(aid, date(2023, 2, 13))
    assert len({t for t in planned.values()}) == 3  # three people, three moments
    # in bed means in bed: the object is in use while they sleep
    assert sim.db.query("SELECT COUNT(*) AS n FROM events WHERE type='action_failure'")[0]["n"] == 0
    fidelity = {r["setting"]: r["class"] for r in sim.cfg.fidelity_table()}
    assert fidelity["planning.at_waking"] == "X"
    assert {r["setting"]: r["class"] for r in sim_config(TRIO).fidelity_table()}["planning.at_waking"] == "P"


def test_at_waking_carries_sleepers_through_midnight_and_plans_at_once_for_whoever_is_up(tmp_path):
    sim = make_sim(tmp_path, TRIO, start="2023-02-13T21:00:00", end="2023-02-14T07:30:00", extra=WAKING)
    sim.run(until=datetime(2023, 2, 14, 0, 5))
    tuesday = date(2023, 2, 14)
    asleep = [aid for aid in TRIO if sim.views()[aid].sleeping]
    assert asleep  # someone had gone to bed before midnight
    for aid in TRIO:
        if aid in asleep:  # still in bed, no plan for the new day yet, and nothing was asked
            assert not sim.planner.has_day(aid, tuesday)
            assert sim.plans.at(aid, PlanLevel.TASK, sim.clock.now).source == "asleep"
        else:  # up past midnight: the new day is planned there and then
            assert sim.planner.has_day(aid, tuesday)
    sim.run()
    assert sim.db.get_meta("status") == "completed"
    early = [aid for aid in asleep if waking_at(sim.identities[aid], tuesday) < datetime(2023, 2, 14, 7, 25)]
    assert early and all(sim.planner.has_day(aid, tuesday) for aid in early)
    # yesterday is summarised from memory when the new day is planned, as without the switch
    assert len(sim.rt.ledger.rows(task="previous_day")) >= len(early)


def test_at_waking_runs_resume_and_replay_like_any_other(tmp_path):
    kw = dict(start="2023-02-13T05:30:00", end="2023-02-13T08:00:00", extra=WAKING)
    a = make_sim(tmp_path, TRIO, name="a", **kw)
    a.run()
    b = make_sim(tmp_path, TRIO, name="b", **kw)
    b.run(max_steps=400)
    b.close()
    b2 = make_sim(tmp_path, TRIO, name="b", **kw)
    b2.run()
    assert b2.db.content_hash(TABLES) == a.db.content_hash(TABLES)
    r = Simulation(sim_config(TRIO, **kw), tmp_path / "replay", replay_from=tmp_path / "a")
    assert r.run() != "failed", r.db.get_meta("stop_detail")
    assert r.db.content_hash(TABLES) == a.db.content_hash(TABLES) and r.rt.budget.usage.calls == 0


# ------------------------------------------------------------------------------------- summaries
def test_a_resident_who_has_lived_nothing_is_not_asked_to_summarise_it():
    llm = CountingLLM(MockLLM(seed=3))
    cfg, db, rt, svc = make_stack(provider=llm, overrides=["summary.min_lived=3"])
    from generative_agents.cognition.summary import SummaryService

    summary = SummaryService(svc)
    now = datetime(2023, 2, 13, 9, 0)
    for text in ("Isabella Rodriguez is a cafe owner.", "Isabella Rodriguez loves to make people feel welcome."):
        svc.remember(ISABELLA, text, MemoryKind.OBSERVATION, MemoryOrigin.SEED, now, importance=5)
    assert summary.dynamic(ISABELLA, now) == "" and not llm.calls
    assert svc.store.count(ISABELLA.id) == 2 and svc.store.count(ISABELLA.id, lived=True) == 0
    for k in range(3):
        svc.remember(ISABELLA, f"Isabella Rodriguez is serving customer number {k}", MemoryKind.OBSERVATION, MemoryOrigin.DIRECT_OBSERVATION, now, importance=3)
    assert summary.dynamic(ISABELLA, now) and {c.task for c in llm.calls} == {"summary_aspect"}  # written once there is a life to read


# ------------------------------------------------------------------------- importance by meaning
class Toy:
    """Vectors with one honest dimension: how momentous a text is (by a few telling words)."""

    is_fixture = False
    model_id, dims, revision = "toy", 8, None
    HEAVY = (
        "break up",
        "college",
        "death",
        "love",
        "wedding",
        "losing",
        "fight",
        "dream",
        "invitation",
        "emergency",
        "office",
        "betrayal",
        "crime",
        "award",
        "illness",
        "decision",
        "proposed",
        "died",
    )

    def embed(self, texts):
        rows = []
        for t in texts:
            heavy = any(w in t.lower() for w in self.HEAVY)
            rng = np.random.default_rng(abs(hash(t)) % 2**32)
            v = np.concatenate([[1.0 if heavy else -1.0], rng.standard_normal(7) * 0.2])
            rows.append(v / np.linalg.norm(v))
        return np.asarray(rows, dtype=np.float32)

    def describe(self):
        return {"kind": "toy"}


def test_importance_by_meaning_rates_from_where_a_memory_sits_between_everyday_and_momentous():
    scorer = MeaningImportance(EmbeddingService(Toy()))
    now = datetime(2023, 2, 13, 9, 0)
    low = scorer.score(ISABELLA, "Klaus is tidying his desk", "observation", now)
    high = scorer.score(ISABELLA, "Maria proposed to Klaus at the cafe", "observation", now)
    assert 1 <= low <= 3 and 7 <= high <= 10
    assert scorer.score(ISABELLA, "the refrigerator is idle", "observation", now) == 1  # the paper's shortcut stays
    batch = scorer.score_batch(ISABELLA, ["bed is idle", "Her grandmother died last night", "Klaus is washing a cup"], now, kind="conversation")
    assert batch[0] == 1 and batch[1] >= 7 and batch[2] <= 3 and scorer.score_batch(ISABELLA, [], now) == []
    # the scale calibrates on the examples themselves, whatever the embedding model
    assert [scorer.rate([t])[0] for t in EVERYDAY[:3]] == [1, 1, 1] and min(scorer.rate(list(MOMENTOUS))) >= 7
    # vectors that tell nothing apart read as everyday, never as an error
    flat = MeaningImportance(EmbeddingService(type("Flat", (Toy,), {"embed": lambda self, texts: np.ones((len(texts), 8), dtype=np.float32)})()))
    assert flat.score(KLAUS, "anything at all", "thought", now) == 1


def test_importance_by_meaning_needs_real_vectors_and_never_keeps_a_scale_made_of_stand_ins():
    # with the lexical fixture there is no meaning to read: the model is asked, as configured otherwise
    _, _, _, fixture = make_stack(overrides=["importance.strategy=meaning"])
    assert isinstance(fixture.importance, ImportanceScorer)
    # a browser pass still waiting for its vectors rates on stand-ins; that scale is thrown away
    waiting = DeferredEmbedding("m", 16)
    service = EmbeddingService(waiting)
    scorer = MeaningImportance(service)
    assert 1 <= scorer.score(ISABELLA, "Klaus is reading", "observation", datetime(2023, 2, 13)) <= 10
    assert service.provisional and scorer._scale is None and len(waiting.missing) == len(EVERYDAY) + len(MOMENTOUS) + 1
    texts = waiting.need()["texts"]
    waiting.deliver(Toy.embed(Toy(), texts)[:, :8].repeat(2, axis=1))
    scorer.score(ISABELLA, "Klaus is reading", "observation", datetime(2023, 2, 13))
    assert not service.provisional and scorer._scale is not None
    with pytest.raises(ValueError, match="expected"):
        waiting.embed(["one more"])
        waiting.deliver(np.ones((3, 16)))
