"""Social memory (research extension): interpretable relationship updates, appraisal, prompt informing, network measures."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from generative_agents.cognition.dialogue import DialogueEngine, Side
from generative_agents.cognition.reaction import ReactionEngine
from generative_agents.cognition.summary import SummaryService
from generative_agents.config import GAConfig, apply_overrides
from generative_agents.db import Database
from generative_agents.providers.mock import MockLLM, ScriptedLLM
from generative_agents.schemas import MemoryKind, MemoryOrigin
from generative_agents.social import network
from generative_agents.social.relationships import RelationshipStore, familiarity_label, valence_label
from generative_agents.social.service import SocialMemory
from helpers import ISABELLA, KLAUS, T, make_sim, make_stack

PAIR = ["isabella_rodriguez", "klaus_mueller"]


def store(**overrides):
    cfg = GAConfig.model_validate(apply_overrides({}, [f"social.{k}={v}" for k, v in overrides.items()]))
    db = Database(None)
    return RelationshipStore(db, cfg.social, step_getter=lambda: 7), db


def test_familiarity_saturates_valence_averages_and_every_update_is_logged():
    st_store, db = store(familiarity_gain_conversation=0.5, valence_rate=0.5, decay_per_day=0)
    a = st_store.record_conversation("a", "b", "B B", T, conversation_id="c1", appraisal=2)
    assert a.familiarity == 0.5 and a.valence == 0.5 and a.conversations == 1 and a.appraisals == 1 and a.first_met_at == T
    a = st_store.record_conversation("a", "b", "B B", T + timedelta(hours=1), conversation_id="c2", appraisal=None)
    assert a.familiarity == 0.75 and a.valence == 0.5 and a.appraisals == 1  # no appraisal: valence untouched
    a = st_store.record_conversation("a", "b", "B B", T + timedelta(hours=2), conversation_id="c3", appraisal=-2)
    assert a.valence == -0.25 and a.familiarity == 0.875
    st_store.flush()
    rows = db.query("SELECT step, kind, json FROM relationship_events ORDER BY id")
    assert len(rows) == 3 and all(r["step"] == 7 and r["kind"] == "conversation" for r in rows)
    first = json.loads(rows[0]["json"])
    assert first["before"] == {"familiarity": 0.0, "valence": 0.0} and first["after"]["familiarity"] == 0.5 and first["conversation_id"] == "c1"
    assert db.one("SELECT json FROM relationships WHERE agent_id='a' AND other_id='b'") is not None
    assert st_store.peek("b", "a") is None  # records are directed; B's side is written only by B's own interactions


def test_presence_counts_once_per_cooldown_and_familiarity_decays_without_contact():
    st_store, _ = store(familiarity_gain_presence=0.1, presence_cooldown_minutes=60, decay_per_day=0)
    assert st_store.record_presence("a", "b", "B", T) is True
    assert st_store.record_presence("a", "b", "B", T + timedelta(minutes=10)) is False
    assert st_store.record_presence("a", "b", "B", T + timedelta(minutes=61)) is True
    st = st_store.get("a", "b")
    assert st.presence == 2 and abs(st.familiarity - 0.19) < 1e-9
    # with decay on, two days without contact halve the familiarity per day before the next gain
    decaying, _ = store(familiarity_gain_presence=0.1, presence_cooldown_minutes=60, decay_per_day=0.5)
    decaying.record_presence("a", "b", "B", T)
    decaying.record_presence("a", "b", "B", T + timedelta(days=2))
    assert abs(decaying.get("a", "b").familiarity - (0.1 * 0.25 + 0.1 * (1 - 0.1 * 0.25))) < 1e-9


def test_describe_renders_only_the_agents_own_record():
    st_store, _ = store(decay_per_day=0)
    assert st_store.describe("a", "b", T, "Ann A", "Bob B") == "Ann A has no record of interacting with Bob B."
    st_store.record_conversation("a", "b", "Bob B", T, conversation_id="c1", appraisal=2)
    text = st_store.describe("a", "b", T, "Ann A", "Bob B")
    assert (
        text.startswith("Ann A's record of Bob B: an acquaintance; 1 conversation (last February 13, 2023, 9:00 am).") and "feels friendly toward Bob" in text
    )
    assert familiarity_label(0.7) == "close" and valence_label(-0.6) == "strained" and valence_label(0.6) == "warm"


def test_appraisal_calls_update_both_sides_and_failures_leave_valence_unchanged():
    cfg, db, rt, svc = make_stack(MockLLM(seed=3), ["social.appraisal=llm"])
    social = SocialMemory(svc, RelationshipStore(db, cfg.social))
    summary = SummaryService(svc)
    conv = DialogueEngine(svc, summary, ReactionEngine(svc, summary)).run(
        Side(ISABELLA, "serving coffee", "Klaus is reading"), Side(KLAUS, "reading", "Isabella is serving coffee"), T, None
    )
    transcript = "\n".join(f"{u.speaker_id}: {u.text}" for u in conv.utterances)
    scores = social.after_conversation(conv, ISABELLA, KLAUS, transcript, T)
    assert set(scores) == {ISABELLA.id, KLAUS.id} and all(isinstance(v, int) for v in scores.values())
    assert len(rt.ledger.rows(task="conversation_appraisal")) == 2
    a, b = social.store.get(ISABELLA.id, KLAUS.id), social.store.get(KLAUS.id, ISABELLA.id)
    assert a.conversations == 1 and b.conversations == 1 and a.appraisals == 1
    # a failing appraisal is recorded as an event and the rating is not invented
    failing = ScriptedLLM({"conversation_appraisal": ['{"valence": 9}', '{"valence": 9}', '{"valence": 9}', '{"valence": 9}']}, fallback=MockLLM(seed=3))
    cfg2, db2, rt2, svc2 = make_stack(failing, ["social.appraisal=llm"])
    social2 = SocialMemory(svc2, RelationshipStore(db2, cfg2.social))
    scores2 = social2.after_conversation(conv, ISABELLA, KLAUS, transcript, T)
    assert scores2 == {ISABELLA.id: None, KLAUS.id: None}
    assert social2.store.get(ISABELLA.id, KLAUS.id).valence == 0.0 and svc2.events.query("appraisal_failure")


def test_prompt_informing_is_off_by_default_and_adds_only_the_observers_own_record():
    cfg, db, rt, svc = make_stack(MockLLM(seed=3))
    summary = SummaryService(svc)
    reaction = ReactionEngine(svc, summary)
    plain, *_ = reaction.context(ISABELLA, KLAUS.name, "Klaus is reading", T, about_agent=True, observed_id=KLAUS.id)
    assert "record" not in plain
    cfg2, db2, rt2, svc2 = make_stack(MockLLM(seed=3), ["social.inform_prompts=true"])
    social = SocialMemory(svc2, RelationshipStore(db2, cfg2.social))
    social.store.record_conversation(ISABELLA.id, KLAUS.id, KLAUS.name, T - timedelta(hours=1), conversation_id="c0", appraisal=1)
    social.store.record_conversation(KLAUS.id, ISABELLA.id, ISABELLA.name, T - timedelta(hours=1), conversation_id="c0", appraisal=-2)
    svc2.remember(ISABELLA, "Klaus Mueller is a regular at Hobbs Cafe", MemoryKind.OBSERVATION, MemoryOrigin.SEED, T - timedelta(hours=2), importance=4)
    reaction2 = ReactionEngine(svc2, SummaryService(svc2))
    reaction2.social = social
    informed, *_ = reaction2.context(ISABELLA, KLAUS.name, "Klaus is reading", T, about_agent=True, observed_id=KLAUS.id)
    assert "Isabella Rodriguez's record of Klaus Mueller" in informed and "feels friendly toward Klaus" in informed
    assert "strained" not in informed  # Klaus's own record of Isabella never leaks into her prompt
    sim_row = rt2.ledger.rows(task="interaction_context")
    assert sim_row and "record of" not in sim_row[-1]["prompt"]  # the record is appended after the summary call, not fed into it


def test_simulation_builds_relationships_from_conversations_and_presence(tmp_path):
    sim = make_sim(tmp_path, PAIR, end="2023-02-13T10:30:00", extra=("social.appraisal=llm",))
    sim.initialize()
    sim.svc.states.get("isabella_rodriguez").tile = (78, 19)
    sim.svc.states.get("klaus_mueller").tile = (76, 19)
    sim.svc.states.flush()
    sim.run(max_steps=120)
    states = sim.social.store.all()
    assert states, "co-presence alone creates relationship records"
    convs = sim.db.query("SELECT id FROM conversations")
    by = {(s.agent_id, s.other_id): s for s in states}
    if convs:
        assert by[("isabella_rodriguez", "klaus_mueller")].conversations >= 1 and by[("klaus_mueller", "isabella_rodriguez")].conversations >= 1
        assert sim.rt.ledger.rows(task="conversation_appraisal")
    assert all(s.presence >= 1 or s.conversations >= 1 for s in states)
    manifest = json.loads((tmp_path / "run" / "manifest.json").read_text())
    assert manifest["social"]["appraisal"] == "llm" and manifest["randomness"]["seed"] == sim.cfg.run.seed
    # the network can be rebuilt at any time from the event log and matches the stored records
    rebuilt = {(s["agent_id"], s["other_id"]): s for s in network.reconstruct(sim.db)}
    for key, st in by.items():
        assert abs(rebuilt[key]["familiarity"] - st.familiarity) < 1e-9 and rebuilt[key]["conversations"] == st.conversations
    earlier = network.reconstruct(sim.db, at=datetime(2023, 2, 13, 9, 0, 5))
    assert sum(s["presence"] + s["conversations"] for s in earlier) <= sum(s.presence + s.conversations for s in states)


def test_network_measures_on_a_hand_built_graph():
    nodes = ["a", "b", "c", "d", "e"]

    def st(a, b, f, v=0.0, conv=1):
        return {"agent_id": a, "other_id": b, "familiarity": f, "valence": v, "conversations": conv, "presence": 0, "appraisals": 1 if v else 0}

    states = [
        st("a", "b", 0.5),
        st("b", "a", 0.5),
        st("b", "c", 0.5),
        st("c", "b", 0.5),
        st("a", "c", 0.5),
        st("c", "a", 0.5),
        st("d", "e", 0.5),
        st("e", "d", 0.1),
        st("a", "d", 0.3, 0.8),
    ]
    m = network.measures(nodes, states, threshold=0.2)
    assert m["edge_count"] == 3 and m["edges"] == [["a", "b"], ["a", "c"], ["b", "c"]]
    assert m["density"] == 0.3 and m["components"] == 3 and m["largest_component"] == 3 and m["isolates"] == 2
    assert m["clustering"] == 1.0 and m["reciprocity"] == round(6 / 8, 4) and m["directed_ties"] == 8
    assert m["mean_valence"] == 0.8 and m["degree"]["d"] == 0
    assert network.measures(["a"], [], 0.2)["density"] is None
