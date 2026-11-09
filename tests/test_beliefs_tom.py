"""Belief ledger and Theory-of-Mind probe (research extension): beliefs stay apart from truth and from prompts."""

from __future__ import annotations

from datetime import timedelta

from eval_helpers import IDS, T0, snapshot, toy_run
from generative_agents.cognition.beliefs import BeliefLedger, detail_values
from generative_agents.evaluation import tom
from generative_agents.evaluation.evidence import Topic
from generative_agents.evaluation.interview import InterviewSession
from generative_agents.providers.embeddings import MockHashEmbedding
from generative_agents.providers.mock import MockLLM
from generative_agents.scenario.loader import load_scenario
from helpers import ISABELLA, KLAUS

PARTY = Topic.from_event("valentines_party", load_scenario("scenarios/pilot5/scenario.yaml").events["valentines_party"])


def test_detail_values_capture_surface_forms():
    v = detail_values(PARTY, "Isabella said: the party at Hobbs Cafe is on February 14th at 5pm")
    assert v == {"date": "february 14", "time": "5pm", "place": "hobbs cafe"}


def test_ledger_separates_first_order_exposure_second_order_grounds_and_truth():
    cfg, db, rt, svc = toy_run()
    ledger = BeliefLedger(db, {"valentines_party": PARTY}, list(IDS))
    b = ledger.beliefs["valentines_party"]
    assert b[ISABELLA.id].holds and b[KLAUS.id].holds and not b["maria_lopez"].holds
    assert b[ISABELLA.id].exposures[0].origin == "seed" and b[KLAUS.id].sources == [ISABELLA.id]
    assert b[KLAUS.id].exposures[0].details == {"date": "february 14", "time": "5pm", "place": "hobbs cafe"}
    # Isabella told Klaus, so she has grounds about him; Klaus heard it from her, so he has grounds about her
    assert b[ISABELLA.id].grounds[KLAUS.id].basis == "told" and b[KLAUS.id].grounds[ISABELLA.id].basis == "heard"
    assert "maria_lopez" not in b[ISABELLA.id].grounds
    second = {(r["agent_id"], r["about"]): r["status"] for r in ledger.second_order("valentines_party")}
    assert second[(ISABELLA.id, KLAUS.id)] == "grounded_true" and second[("maria_lopez", KLAUS.id)] == "no_grounds_true"
    assert second[(ISABELLA.id, "maria_lopez")] == "no_grounds_false"
    s = ledger.summary()["topics"]["valentines_party"]
    assert s["holders"] == [ISABELLA.id, KLAUS.id] and s["grounded_true"] == 2 and s["knowledge_coverage"] == 0.5
    # a reference time before the conversation hides it from both the beliefs and the grounds
    early = BeliefLedger(db, {"valentines_party": PARTY}, list(IDS), before=T0 + timedelta(hours=1))
    assert not early.beliefs["valentines_party"][KLAUS.id].holds and early.beliefs["valentines_party"][ISABELLA.id].grounds == {}


def test_conflicting_detail_values_are_flagged_for_review():
    from generative_agents.schemas import MemoryKind, MemoryOrigin

    cfg, db, rt, svc = toy_run()
    svc.remember(
        KLAUS,
        'Maria Lopez said to Klaus Mueller: "the Valentine\'s party is at 17:00"',
        MemoryKind.OBSERVATION,
        MemoryOrigin.STATEMENT,
        T0 + timedelta(hours=11),
        importance=5,
        speaker_id="maria_lopez",
    )
    ledger = BeliefLedger(db, {"valentines_party": PARTY}, list(IDS))
    kb = ledger.beliefs["valentines_party"][KLAUS.id]
    assert kb.conflicting_details() == ["time"] and set(kb.detail_variants()["time"]) == {"5pm", "17 00"}
    assert ledger.summary()["topics"]["valentines_party"]["with_conflicting_details"] == [KLAUS.id]


def test_tom_probe_compares_claims_with_grounds_and_truth(tmp_path):
    cfg, db, rt, svc = toy_run()
    snap = snapshot(db, tmp_path / "final.sqlite")
    ledger = BeliefLedger(db, {"valentines_party": PARTY}, list(IDS))
    session = InterviewSession(cfg, snap, ledger_path=None, scope="tom-test", provider=MockLLM(seed=3), embedding_provider=MockHashEmbedding(128))
    try:
        rows = tom.probe_tom(session, PARTY, list(IDS), ledger)
        calls = session.rt.ledger.rows()
    finally:
        session.close()
    assert len(rows) == 6 and all(r["question"].startswith("Does ") for r in rows)
    by = {(r["agent_id"], r["about"]): r for r in rows}
    assert by[(ISABELLA.id, KLAUS.id)]["grounds"] == "told" and by[(ISABELLA.id, KLAUS.id)]["other_holds"] is True
    assert by[("maria_lopez", KLAUS.id)]["grounds"] is None
    assert {r["label"] for r in rows} <= {
        "grounded_correct",
        "ungrounded_correct",
        "over_attribution",
        "under_attribution",
        "unaware_of_other",
        "correct_negative",
    }
    assert all(r["label"] in ("correct_negative", "over_attribution") for r in rows if r["about"] == "maria_lopez")  # Maria does not know
    summ = tom.summarize(rows)
    assert summ["pairs"] == 6 and sum(summ["labels"].values()) == 6
    # prompts never carried the ledger or the truth
    for call in calls:
        assert "grounds" not in call["prompt"] and "other_holds" not in call["prompt"]
    assert (
        tom.label(True, True, True) == "grounded_correct"
        and tom.label(False, True, True) == "under_attribution"
        and tom.label(None, True, True) == "label_failed"
    )
