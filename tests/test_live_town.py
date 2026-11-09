"""A town that stays live: memoized mechanical prompts (ledger-answered repeats) and the live configs."""

from __future__ import annotations

import json

from generative_agents.config import load_config
from generative_agents.prompting import PromptRegistry
from generative_agents.providers.base import TaskFailed
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.gateway import GatewaySettings, LLMGateway
from generative_agents.providers.ledger import CallLedger
from generative_agents.providers.mock import MockLLM, ScriptedLLM
from generative_agents.simulation.budget import Budget
from generative_agents.simulation.engine import Simulation
from helpers import CountingLLM, sim_config
from test_gateway import imp_vars

PAIR = ["isabella_rodriguez", "klaus_mueller"]
TABLES = ("memories", "plans", "conversations", "agent_state", "spatial_memory", "world_objects", "relationships")


def memo_gateway(provider, ledger=None, tasks=("importance",), replay=False):
    return LLMGateway(
        provider,
        PromptRegistry(),
        ledger or CallLedger(None, scope="live"),
        Budget(),
        GatewaySettings(model="m", max_retries=0, max_validation_repairs=1, backoff_s=0, memoize_tasks=frozenset(tasks)),
        replay=replay,
        sleep=lambda s: None,
    )


def test_memoized_tasks_answer_exact_repeats_from_the_first_valid_reply():
    provider = ScriptedLLM({"importance": [{"rating": 2}, {"rating": 9}]})
    gw = memo_gateway(provider)
    a = gw.run("importance", imp_vars("same text"))
    b = gw.run("importance", imp_vars("same text"))
    assert (a.output.rating, b.output.rating) == (2, 2) and not a.cached and b.cached  # the repeat never reached the model
    assert gw.budget.usage.calls == 1 and gw.budget.usage.cache_hits == 1 and len(provider.calls) == 1
    assert gw.run("importance", imp_vars("other text")).output.rating == 9  # a new prompt is a new call
    # a task that is not memoized keeps the paper's behavior: identical prompts are sampled again
    other = ScriptedLLM({"importance": [{"rating": 2}, {"rating": 9}]})
    plain = memo_gateway(other, tasks=())
    assert [plain.run("importance", imp_vars("same text")).output.rating for _ in range(2)] == [2, 9]


def test_invalid_and_repaired_replies_are_never_memoized():
    provider = ScriptedLLM({"importance": ['{"rating": 42}', '{"rating": 4}', '{"rating": 7}']})
    gw = memo_gateway(provider)
    first = gw.run("importance", imp_vars("x"))  # invalid, then repaired to 4 (the repair prompt is a different request)
    assert first.output.rating == 4 and len(first.call_ids) == 2
    second = gw.run("importance", imp_vars("x"))
    assert second.output.rating == 7 and not second.cached  # the original prompt's only record is invalid, so it is sampled again
    assert gw.ledger.lookup_memo(gw.request_hash(_request(gw, "x"))) is None
    failing = ScriptedLLM({"importance": ['{"rating": 0}', '{"rating": 0}']})
    gw2 = memo_gateway(failing)
    try:
        gw2.run("importance", imp_vars("bad"))
        raise AssertionError("should fail")
    except TaskFailed:
        pass
    assert gw2.ledger.lookup_memo(gw2.request_hash(_request(gw2, "bad"))) is None


def _request(gw, text):
    """The initial importance request for ``text``, as the gateway would build it (for hash lookups)."""

    from generative_agents.providers.base import LLMRequest
    from generative_agents.providers.schema import strict_json_schema

    tpl = gw.registry.get("importance")
    system, prompt = tpl.render(imp_vars(text))
    return LLMRequest(
        task="importance",
        template_id=tpl.template_id,
        template_hash=tpl.sha256,
        system=system,
        prompt=prompt,
        output_schema=strict_json_schema(tpl.output_model),
        model="m",
        max_output_tokens=tpl.max_output_tokens,
    )


def test_a_memoized_town_makes_fewer_calls_and_still_replays_exactly(tmp_path):
    memo = ("providers.llm.memoize_tasks=[choose_location, importance, importance_batch, action_grounding]",)
    plain = Simulation(
        sim_config(PAIR, end="2023-02-13T11:00:00"), tmp_path / "plain", provider=CountingLLM(MockLLM(seed=5)), embedding_provider=MockHashEmbedding(128)
    )
    assert plain.run() == "completed"
    live = Simulation(
        sim_config(PAIR, end="2023-02-13T11:00:00", extra=memo),
        tmp_path / "live",
        provider=CountingLLM(MockLLM(seed=5)),
        embedding_provider=MockHashEmbedding(128),
    )
    assert live.run() == "completed"
    assert len(live.rt.provider.calls) < len(plain.rt.provider.calls)
    assert live.rt.budget.usage.cache_hits > 0
    manifest = json.loads((tmp_path / "live" / "manifest.json").read_text())
    assert {r["setting"]: r["class"] for r in manifest["fidelity"]}["providers.llm.memoize_tasks"] == "X"
    replay = Simulation(sim_config(PAIR, end="2023-02-13T11:00:00", extra=memo), tmp_path / "replay", replay_from=tmp_path / "live")
    assert replay.run() != "failed" and replay.db.content_hash(TABLES) == live.db.content_hash(TABLES)
    assert replay.rt.budget.usage.calls == 0


def test_live_configs_are_open_ended_and_route_work_to_the_small_model():
    for name, n in (("configs/town_live.yaml", 10), ("configs/town_live_25.yaml", None)):
        cfg = load_config(name)
        assert cfg.game.enabled and (cfg.scenario.end - cfg.scenario.start).days > 90
        assert set(cfg.providers.llm.memoize_tasks) == {"choose_location", "importance", "importance_batch", "action_grounding"}
        assert set(cfg.providers.llm.memoize_tasks) <= set(cfg.providers.llm.task_overrides)  # memoized tasks are the small-model tasks
        assert cfg.retrieval.forgetting.enabled and cfg.output.snapshots == ["initial"]
        assert (len(cfg.scenario.population) if cfg.scenario.population else None) == n
