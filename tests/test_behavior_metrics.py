"""Behavioral, adaptation and retrieval-probe measures (research extension) on small offline runs."""

from __future__ import annotations

from datetime import datetime

import yaml

from generative_agents.evaluation import behavior as beh
from generative_agents.evaluation import memory_probe as mp
from generative_agents.memory.retrieval import Forgetting, RetrievalSettings
from generative_agents.providers.embeddings import MockHashEmbedding
from helpers import make_sim, sim_config

PAIR = ["isabella_rodriguez", "klaus_mueller"]


def test_behavior_measures_count_scheduled_actions_blocks_and_idleness(tmp_path):
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T11:00:00")
    sim.run()
    b = beh.behavior(sim.db, PAIR, start=sim.cfg.scenario.start, end=sim.clock.now)
    for aid in PAIR:
        a = b["agents"][aid]
        assert a["actions"] >= 1 and 0 <= a["scheduled_share"] <= 1 and a["hour_blocks"] >= 1
        assert 0 <= a["plan_adherence"] <= 1 and a["idle_share"] is not None
        assert a["reaction_decisions"] == sum(a["reactions"].values())
    p = b["pooled"]
    assert p["scheduled_share"] is not None and p["plan_adherence"] is not None and p["plan_failures"] == 0
    hours = beh.behavior_by_hour(sim.db, PAIR)
    assert hours and all(h["hour"].endswith(":00") for h in hours) and sum(h.get("action", 0) for h in hours) == sum(a["actions"] for a in b["agents"].values())


def test_adaptation_measures_find_reactions_and_mentions_after_an_intervention(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    at = "2023-02-13T09:05:00"
    (run_dir / "interventions.yaml").write_text(
        yaml.safe_dump(
            {
                "interventions": [
                    {
                        "kind": "ambient",
                        "at": at,
                        "id": "fire1",
                        "tile": [78, 19],
                        "subject": "fire",
                        "predicate": "is",
                        "object": "burning",
                        "description": "a fire is burning in Hobbs Cafe",
                        "until": "2023-02-13T10:00:00",
                    },
                    {"kind": "object_state", "at": at, "address": "the Ville:Hobbs Cafe:cafe:cooking area", "state": "burning"},
                ]
            }
        )
    )
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T10:30:00")
    sim.initialize()
    for aid in PAIR:
        sim.svc.states.get(aid).tile = (78, 20)
    sim.svc.states.flush()
    sim.run()
    assert sim.svc.events.query("intervention")
    out = beh.adaptation(sim.db, PAIR, datetime.fromisoformat(at), ["fire", "burning"], window_minutes=90)
    assert out["at"] == at and set(out["agents"]) == set(PAIR)
    assert out["perceived"], "someone standing in the cafe should perceive the fire"
    assert out["changed_plans"] and out["changed_share"] > 0 and out["median_latency_minutes"] is not None
    assert all(a["latency_minutes"] is None or a["latency_minutes"] >= 0 for a in out["agents"].values())
    assert out["changed_share_among_perceivers"] is not None
    control = beh.adaptation(sim.db, PAIR, datetime.fromisoformat("2023-02-13T08:00:00"), ["volcano"], window_minutes=30)
    assert control["changed_plans"] == [] and control["mentions_in_conversation"] == 0


def test_planted_facts_probe_isolates_the_retrieval_mechanism(tmp_path):
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T09:30:00")
    sim.run()
    snap = tmp_path / "run" / "snapshots" / "final.sqlite"
    before = snap.read_bytes()
    res = mp.planted_facts(sim.cfg, snap, PAIR, k=10, embedding_provider=MockHashEmbedding(128))
    assert snap.read_bytes() == before and sim.db.one("SELECT COUNT(*) n FROM memories WHERE metadata_json LIKE '%probe%'")["n"] == 0
    s = res["summary"]
    assert s["n"] == 8 * len(PAIR) and 0 <= s["recall_at_k"] <= 1 and set(s["by_age"]) <= {"<=1h", "<=6h", "<=24h", ">24h"}
    assert s["forgotten"] == 0 and res["embedding_model"].startswith("mock-hash")
    # with aggressive forgetting the old facts become inaccessible and recall drops for them
    harsh = RetrievalSettings.from_config(sim.cfg.retrieval)
    harsh.forgetting = Forgetting(enabled=True, decay=0.5, threshold=-0.8, importance_bonus=0.0)
    res2 = mp.planted_facts(sim.cfg, snap, PAIR, k=10, embedding_provider=MockHashEmbedding(128), settings=harsh)
    assert res2["summary"]["forgotten"] >= 2 and res2["summary"]["by_age"][">24h"] == 0.0
    assert res2["summary"]["recall_at_k"] <= s["recall_at_k"]


def test_own_experience_probe_reports_conversation_recall(tmp_path):
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T10:30:00")
    sim.initialize()
    sim.svc.states.get("isabella_rodriguez").tile = (78, 19)
    sim.svc.states.get("klaus_mueller").tile = (76, 19)
    sim.svc.states.flush()
    sim.run()
    snap = tmp_path / "run" / "snapshots" / "final.sqlite"
    res = mp.own_experiences(sim.cfg, snap, PAIR, k=10, embedding_provider=MockHashEmbedding(128))
    import json

    n_conv = sum(1 for r in sim.db.query("SELECT json FROM conversations") if json.loads(r["json"]).get("utterances"))
    if n_conv:
        assert res["summary"]["n"] == 2 * n_conv and res["summary"]["recall_at_k"] is not None
        assert all(r["age_hours"] is not None for r in res["rows"])
    else:
        assert res["summary"]["n"] == 0


def test_sim_config_helper_round_trip():
    cfg = sim_config(PAIR)
    assert cfg.scenario.population == PAIR
