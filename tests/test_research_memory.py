"""Research extensions to memory and planning: activation-based forgetting and the hourly-only planner."""

from __future__ import annotations

import math
from datetime import timedelta

from conftest import T0, hours
from generative_agents.cognition.planning import Planner, PlanStore
from generative_agents.cognition.summary import SummaryService
from generative_agents.config import GAConfig, apply_overrides
from generative_agents.memory.retrieval import Forgetting, RetrievalSettings, Retriever
from generative_agents.memory.trace import TraceStore
from generative_agents.providers.mock import MockLLM
from generative_agents.schemas import PlanLevel
from helpers import KLAUS, make_stack


def test_activation_follows_the_act_r_base_level_form(env):
    f = Forgetting(enabled=True, decay=0.5, threshold=-1.0, importance_bonus=0.0)
    fresh = env.add("a", "fresh", created=T0, importance=1)
    assert math.isclose(f.activation(fresh, T0), math.log(2.0))
    old = env.add("a", "old", created=T0 - hours(48), importance=1)
    expected = math.log(2 * 49**-0.5)
    assert math.isclose(f.activation(old, T0), expected) and expected < -1.0
    # a recent retrieval refreshes one trace and lifts the activation back above the threshold
    env.store.touch([old.id], T0 - hours(1))
    old.last_accessed_at = T0 - hours(1)
    assert f.activation(old, T0) > -1.0
    # importance adds a fixed bonus per point above one
    f2 = Forgetting(enabled=True, decay=0.5, threshold=-1.0, importance_bonus=0.1)
    strong = env.add("a", "strong", created=T0 - hours(48), importance=10)
    assert math.isclose(f2.activation(strong, T0), expected + 0.9)


def test_forgotten_memories_are_excluded_before_scoring_and_recorded_in_the_trace(env):
    now = T0
    kept = env.add("a", "the party is at Hobbs Cafe", created=now - hours(2), importance=5)
    gone = env.add("a", "the party is at Hobbs Cafe tonight", created=now - hours(72), importance=2)
    important = env.add("a", "the party is at Hobbs Cafe at 5pm", created=now - hours(72), importance=10)
    settings = RetrievalSettings(budget_tokens=None, max_items=None, forgetting=Forgetting(enabled=True, decay=0.5, threshold=-1.0, importance_bonus=0.1))
    traces = TraceStore(env.db)
    r = Retriever(env.store, env.embedder, settings, trace_sink=traces.sink)
    res = r.retrieve("a", "party at Hobbs Cafe", now, purpose="test")
    delivered = {m.id for m in res.delivered}
    assert kept.id in delivered and important.id in delivered and gone.id not in delivered
    ex = [e for e in res.excluded if e["id"] == gone.id]
    assert ex and ex[0]["reason"].startswith("forgotten") and ex[0]["activation"] < -1.0
    trace = traces.get(res.trace_id)
    assert any(e["id"] == gone.id for e in trace["excluded"])
    assert env.store.get(gone.id) is not None  # nothing is deleted
    # off by default: the same query delivers everything
    plain = Retriever(env.store, env.embedder, RetrievalSettings(budget_tokens=None, max_items=None))
    assert {m.id for m in plain.retrieve("a", "party at Hobbs Cafe", now, commit_access=False).delivered} == {kept.id, gone.id, important.id}


def test_forgetting_settings_come_from_config():
    cfg = GAConfig.model_validate(apply_overrides({}, ["retrieval.forgetting.enabled=true", "retrieval.forgetting.threshold=-0.5"]))
    s = RetrievalSettings.from_config(cfg.retrieval)
    assert s.forgetting.enabled and s.forgetting.threshold == -0.5
    assert {r["setting"]: r["class"] for r in cfg.fidelity_table()}["retrieval.forgetting"] == "X"


def test_hourly_only_planner_follows_blocks_without_decomposition_calls():
    cfg, db, rt, svc = make_stack(MockLLM(seed=11), ["planning.decompose=false"])
    plans = PlanStore(db)
    planner = Planner(svc, SummaryService(svc), plans)
    d0 = T0.replace(hour=0)
    planner.ensure_day(KLAUS, d0)
    t = d0 + timedelta(hours=9, minutes=20)
    task = planner.current_task(KLAUS, t)
    block = plans.get(task.parent_id)
    assert task.start == block.start and task.end == block.end and task.description == block.description
    assert task.metadata.get("decompose") is False and rt.ledger.rows(task="decompose") == []
    # an interruption resumes the block without a replan call
    planner.insert(KLAUS, t, "chat with a neighbor", 10, source="reaction")
    after = [x for x in plans.items(KLAUS.id, level=PlanLevel.TASK) if x.start >= t + timedelta(minutes=10) and x.parent_id == block.id]
    assert after and after[0].description == block.description and rt.ledger.rows(task="replan") == []
