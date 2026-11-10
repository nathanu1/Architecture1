"""Switches that make a live town cheap enough to stay online (docs/deploy.md §2c-§2d):
the structured habit cache, the reaction salience gate, client-side rate limits and named
provider pools. Each is off by default and recorded in the manifest when on."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from generative_agents.config import GAConfig, apply_overrides, load_config
from generative_agents.db import iso
from generative_agents.prompting import PromptRegistry
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.gateway import GatewaySettings, LLMGateway
from generative_agents.providers.ledger import CallLedger
from generative_agents.providers.mock import MockLLM, ScriptedLLM
from generative_agents.providers.ratelimit import RateLimitedProvider, RateLimiter, RateLimits
from generative_agents.simulation.budget import Budget
from generative_agents.simulation.engine import Simulation
from helpers import CountingLLM, make_sim, sim_config
from test_gateway import imp_vars

PAIR = ["isabella_rodriguez", "klaus_mueller"]
TRIO = ["isabella_rodriguez", "klaus_mueller", "maria_lopez"]
TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")
MECHANICAL = "[choose_location, importance, importance_batch, action_grounding]"


def gateway(provider, *, habit=("importance",), overrides=None, pools=None, pool_models=None, ledger=None, replay=False):
    return LLMGateway(
        provider,
        PromptRegistry(),
        ledger or CallLedger(None, scope="cheap"),
        Budget(),
        GatewaySettings(
            model="m", max_retries=0, max_validation_repairs=1, backoff_s=0, habit_tasks=frozenset(habit), task_overrides=overrides, pool_models=pool_models
        ),
        replay=replay,
        sleep=lambda s: None,
        pools=pools,
    )


# ---------------------------------------------------------------------------------------- habits
def test_a_habit_answers_the_same_structured_situation_whatever_the_prompt_says():
    provider = ScriptedLLM({"importance": [{"rating": 3}, {"rating": 8}]})
    gw = gateway(provider)
    first = gw.run("importance", imp_vars("the cafe opens"), agent_id="isabella_rodriguez")
    changed = dict(imp_vars("the cafe opens"), agent_summary="a different dynamic summary on another day")
    second = gw.run("importance", changed, agent_id="isabella_rodriguez")
    assert (first.output.rating, second.output.rating) == (3, 3) and second.cached and not first.cached
    assert len(provider.calls) == 1 and gw.budget.usage.cache_hits == 1
    # a different agent, or a different structured input, is a different situation
    assert gw.run("importance", imp_vars("the cafe opens"), agent_id="klaus_mueller").output.rating == 8
    assert len(provider.calls) == 2


def test_habits_need_structured_inputs_and_are_never_formed_from_invalid_replies():
    bare = {k: v for k, v in imp_vars("x").items() if not k.startswith("_")}
    assert LLMGateway.habit_key("importance", PromptRegistry().get("importance"), {"model": "m"}, "a", bare) is None
    provider = ScriptedLLM({"importance": ['{"rating": 42}', '{"rating": 4}', '{"rating": 9}']})
    gw = gateway(provider)
    assert gw.run("importance", imp_vars("y"), agent_id="a").output.rating == 4  # invalid, repaired
    # the repaired reply is a valid answer to the situation and becomes the habit
    assert gw.run("importance", imp_vars("y"), agent_id="a").output.rating == 4
    assert len(provider.calls) == 2
    # a task outside habit_tasks is sampled every time
    other = ScriptedLLM({"importance": [{"rating": 1}, {"rating": 2}]})
    plain = gateway(other, habit=())
    assert [plain.run("importance", imp_vars("z"), agent_id="a").output.rating for _ in range(2)] == [1, 2]


def test_a_town_with_habits_calls_the_model_less_and_still_replays_exactly(tmp_path):
    habits = (f"providers.llm.habit_tasks={MECHANICAL}",)
    plain = Simulation(
        sim_config(PAIR, end="2023-02-13T11:00:00"), tmp_path / "plain", provider=CountingLLM(MockLLM(seed=5)), embedding_provider=MockHashEmbedding(128)
    )
    assert plain.run() == "completed"
    cheap = Simulation(
        sim_config(PAIR, end="2023-02-13T11:00:00", extra=habits),
        tmp_path / "cheap",
        provider=CountingLLM(MockLLM(seed=5)),
        embedding_provider=MockHashEmbedding(128),
    )
    assert cheap.run() == "completed"
    by_task = lambda sim: {t: sum(1 for r in sim.rt.provider.calls if r.task == t) for t in ("choose_location", "importance")}  # noqa: E731
    assert len(cheap.rt.provider.calls) < len(plain.rt.provider.calls) and cheap.rt.budget.usage.cache_hits > 0
    assert all(by_task(cheap)[t] <= by_task(plain)[t] for t in by_task(plain))
    manifest = json.loads((tmp_path / "cheap" / "manifest.json").read_text())
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["providers.llm.habit_tasks"] == "X"
    assert cheap.rt.ledger.conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0] > 0
    replay = Simulation(sim_config(PAIR, end="2023-02-13T11:00:00", extra=habits), tmp_path / "replay", replay_from=tmp_path / "cheap")
    assert replay.run() != "failed" and replay.db.content_hash(TABLES) == cheap.db.content_hash(TABLES)
    assert replay.rt.budget.usage.calls == 0


# ---------------------------------------------------------------------------------- salience gate
def test_the_salience_gate_waves_through_a_routine_observation_within_its_cooldown(tmp_path):
    sim = make_sim(tmp_path, PAIR, extra=("reaction.salience_gate=true", "reaction.routine_cooldown_minutes=30"))
    sim.initialize()
    st = sim.svc.states.get("isabella_rodriguez")
    now = sim.clock.now
    key = "Klaus Mueller|is|reading"
    assert not sim._routine(st, key, now)  # never seen: deliberate
    st.extra.setdefault("routine", {})[key] = iso(now)
    assert sim._routine(st, key, now + timedelta(minutes=10))  # routine: skip the model
    assert not sim._routine(st, key, now + timedelta(minutes=31))  # cooldown over: deliberate again
    off = make_sim(tmp_path, PAIR, name="off")
    off.initialize()
    st2 = off.svc.states.get("isabella_rodriguez")
    st2.extra.setdefault("routine", {})[key] = iso(now)
    assert not off._routine(st2, key, now)  # the gate is off by default


def test_a_gated_town_deliberates_no_more_often_than_an_ungated_one_and_logs_what_it_skipped(tmp_path):
    def run(name, extra=()):
        sim = make_sim(tmp_path, TRIO, name=name, end="2023-02-13T11:30:00", extra=extra)
        sim.initialize()
        for aid, tile in zip(TRIO, [(78, 19), (76, 19), (77, 20)], strict=True):
            sim.svc.states.get(aid).tile = tile
        sim.svc.states.flush()
        sim.run(max_steps=240)
        return sim

    plain = run("plain")
    gated = run("gated", ("reaction.salience_gate=true",))
    reactions = lambda sim: len(sim.svc.events.query("reaction"))  # noqa: E731
    assert reactions(gated) <= reactions(plain)
    skipped = gated.svc.events.query("reaction_gated")
    assert not plain.svc.events.query("reaction_gated")
    for ev in skipped:
        assert ev["key"] and ev["observation"] and ev["agent_id"] in TRIO
    manifest = json.loads((tmp_path / "gated" / "manifest.json").read_text())
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["reaction.salience_gate"] == "X"


# ------------------------------------------------------------------------------------ rate limits
class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def test_the_limiter_waits_before_a_call_that_would_cross_a_plan_limit():
    clock = Clock()
    lim = RateLimiter(RateLimits(requests_per_minute=10, tokens_per_minute=1000, headroom=1.0), clock=clock.now, sleep=clock.sleep)
    for _ in range(10):
        assert lim.acquire(50) == 0
    waited = lim.acquire(50)  # the 11th request in the same minute waits for the first to age out
    assert waited == pytest.approx(60.0) and clock.slept == [pytest.approx(60.0)]
    clock.t += 1
    assert lim.acquire(900) == 0  # 950 of 1000 tokens in the window
    assert lim.acquire(100) > 0  # tokens, not requests, are the binding limit now
    snap = lim.snapshot()
    assert snap["waits"] == 2 and snap["minute"]["tokens"] <= 1000


def test_the_daily_limit_holds_across_minutes_and_settles_to_real_usage():
    clock = Clock()
    lim = RateLimiter(RateLimits(requests_per_day=3, headroom=1.0), clock=clock.now, sleep=clock.sleep)
    for _ in range(3):
        lim.acquire(1)
        clock.t += 120
    assert lim.acquire(1) == pytest.approx(86_400 - 360)  # waits until the first request leaves the day window
    lim2 = RateLimiter(RateLimits(tokens_per_minute=100, headroom=1.0), clock=clock.now, sleep=clock.sleep)
    lim2.acquire(90)
    lim2.settle(90, 20)  # the provider reported 20 tokens: the reservation shrinks
    assert lim2.acquire(70) == 0


def test_a_rate_limited_provider_is_transparent_to_the_gateway_and_describes_its_plan():
    clock = Clock()
    inner = ScriptedLLM({"importance": [{"rating": 5}, {"rating": 6}, {"rating": 7}]})
    limited = RateLimitedProvider(inner, RateLimits(requests_per_minute=2, headroom=1.0), clock=clock.now, sleep=clock.sleep)
    gw = gateway(limited, habit=())
    for expected in (5, 6, 7):
        assert gw.run("importance", imp_vars(str(expected))).output.rating == expected
    assert clock.slept and clock.slept[0] == pytest.approx(60.0)  # the third call waited a minute
    assert limited.describe()["rate_limit"] == {"requests_per_minute": 2, "headroom": 1.0}
    assert gw.ledger.rows()[0]["provider"] == "scripted"  # the wrapper keeps the inner provider's name


# ------------------------------------------------------------------------------------------ pools
def test_tasks_route_to_named_pools_with_their_own_model_and_the_ledger_says_which():
    default = ScriptedLLM({"importance": [{"rating": 1}]}, fallback=MockLLM(seed=1))
    small = ScriptedLLM({"importance": [{"rating": 9}]})
    gw = gateway(default, habit=(), overrides={"importance": {"provider": "small"}}, pools={"small": small}, pool_models={"small": "tiny-3b"})
    res = gw.run("importance", imp_vars("routed"))
    assert res.output.rating == 9 and small.calls[0].model == "tiny-3b" and small.calls[0].pool == "small" and not default.calls
    assert gw.ledger.rows()[0]["provider"] == "small:scripted" and gw.ledger.rows()[0]["model"] == "tiny-3b"
    # tasks without an override stay on the default provider
    gw.run(
        "choose_location",
        {
            "agent_summary": "s",
            "agent_name": "A",
            "current_place": "p",
            "current_children": "",
            "level": "area",
            "level_plural": "areas",
            "options": "x, y",
            "activity": "a",
            "_options": ["x", "y"],
            "_activity": "a",
            "_home": "",
            "_room": "",
            "_current": None,
        },
    )
    assert [r.task for r in default.calls] == ["choose_location"]
    with pytest.raises(ValueError, match="unknown provider pool"):
        gateway(default, habit=(), overrides={"importance": {"provider": "nope"}})


def test_pool_config_resolves_names_and_builds_rate_limited_providers(tmp_path):
    with pytest.raises(ValueError, match="names no entry"):
        GAConfig.model_validate(apply_overrides({}, ["providers.llm.task_overrides.importance.provider=nope"]))
    extra = (
        "providers.llm.pools.small.kind=mock",
        "providers.llm.pools.small.model=mock-small",
        "providers.llm.pools.small.rate_limit.requests_per_minute=100000",
        "providers.llm.task_overrides.importance.provider=small",
        "providers.llm.rate_limit.requests_per_day=100000",
    )
    sim = Simulation(sim_config(PAIR, end="2023-02-13T10:00:00", extra=extra), tmp_path / "pooled", embedding_provider=MockHashEmbedding(128))
    assert sim.run() == "completed"
    assert isinstance(sim.rt.provider, RateLimitedProvider) and isinstance(sim.rt.gateway.pools["small"], RateLimitedProvider)
    rows = sim.rt.ledger.rows(task="importance")
    assert rows and all(r["provider"] == "small:mock" and r["model"] == "mock-small" for r in rows)
    assert all(r["provider"] == "mock" for r in sim.rt.ledger.rows(task="choose_location"))
    manifest = json.loads((tmp_path / "pooled" / "manifest.json").read_text())
    assert manifest["llm_pools"]["small"]["rate_limit"] == {"requests_per_minute": 100000, "headroom": 0.9}
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["providers.llm.pools"] == "E"
    # a replay of a pooled run makes no calls at all
    replay = Simulation(sim_config(PAIR, end="2023-02-13T10:00:00", extra=extra), tmp_path / "replay", replay_from=tmp_path / "pooled")
    assert replay.run() != "failed" and replay.rt.budget.usage.calls == 0 and replay.db.content_hash(TABLES) == sim.db.content_hash(TABLES)


def test_live_configs_turn_the_cheap_switches_on():
    for name in ("configs/town_live.yaml", "configs/town_live_25.yaml"):
        cfg = load_config(name)
        assert (
            set(cfg.providers.llm.habit_tasks)
            == set(cfg.providers.llm.memoize_tasks)
            == {"choose_location", "importance", "importance_batch", "action_grounding"}
        )
        assert cfg.reaction.salience_gate and cfg.engine.parallel_calls == 4 and cfg.game.enabled
        on = {r["setting"] for r in cfg.fidelity_table() if r["class"] == "X"}
        assert {"providers.llm.habit_tasks", "providers.llm.memoize_tasks", "reaction.salience_gate", "engine.parallel_calls"} <= on


def test_the_real_model_experiment_keeps_the_cost_switches_off_and_plans_twelve_runs():
    from generative_agents.evaluation.experiment import Protocol

    base = load_config("configs/social_day_llama.yaml")
    llm = base.providers.llm
    assert llm.kind == "ollama" and not llm.memoize_tasks and not llm.habit_tasks and not base.reaction.salience_gate
    assert not base.retrieval.forgetting.enabled and not base.game.enabled and base.engine.parallel_calls == 4
    assert len(base.scenario.population) == 10
    mock, real = (Protocol.load(f"configs/experiments/social_network_{kind}.yaml") for kind in ("mock", "llama"))
    assert real.conditions == mock.conditions and real.seeds == mock.seeds and real.determinism_check
    assert set(mock.primary_outcomes) <= set(real.primary_outcomes)
