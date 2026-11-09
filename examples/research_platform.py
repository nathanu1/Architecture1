"""A short tour of the research platform on the offline MOCK model (no credentials, under a minute).

It runs a small town for one morning, then shows what the extensions make measurable:
relationship records and network measures, behavioral measures, the belief ledger with
second-order grounds, a planted-fact retrieval probe under two forgetting settings, and a
counterfactual fork in which a fire breaks out in Hobbs Cafe. Everything printed comes from
recorded data; the mock's words are mechanical, so read this as a pipeline demonstration.

    python examples/research_platform.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generative_agents.cognition.beliefs import BeliefLedger  # noqa: E402
from generative_agents.config import GAConfig, apply_overrides, repo_path  # noqa: E402
from generative_agents.db import Database  # noqa: E402
from generative_agents.evaluation import behavior as beh  # noqa: E402
from generative_agents.evaluation import memory_probe as mp  # noqa: E402
from generative_agents.evaluation.evidence import load_topics  # noqa: E402
from generative_agents.memory.retrieval import Forgetting, RetrievalSettings  # noqa: E402
from generative_agents.scenario.loader import load_scenario  # noqa: E402
from generative_agents.simulation.engine import Simulation, load_run_config, save_config  # noqa: E402
from generative_agents.simulation.fork import fork_run  # noqa: E402
from generative_agents.social import network  # noqa: E402

POP = ["isabella_rodriguez", "maria_lopez", "klaus_mueller", "wolfgang_schulz"]


def section(title: str) -> None:
    print(f"\n=== {title}")


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="hearthside-research-"))
    cfg = GAConfig.model_validate(
        apply_overrides(
            {},
            [
                "scenario.path=scenarios/pilot5/scenario.yaml",
                f"scenario.population=[{', '.join(POP)}]",
                "scenario.start=2023-02-13T06:00:00",
                "scenario.end=2023-02-13T14:00:00",
                "output.checkpoint_every_steps=180",
                "output.snapshots=[initial, '2023-02-13T12:00:00', final]",
                "social.appraisal=llm",
                "run.label=research platform tour (MOCK)",
            ],
        )
    )
    base = work / "base"
    base.mkdir()
    save_config(cfg, base)
    sim = Simulation(cfg, base)
    status = sim.run()
    print(f"base run: {status} at {sim.clock.now} with {sim.rt.ledger.totals()['calls']} mock calls → {base}")
    agents = list(sim.order)
    names = {a: sim.identities[a].name for a in agents}

    section("Social memory: each agent's own relationship records")
    for st in sim.social.store.all():
        print(
            f"  {names[st.agent_id]:<20} → {names[st.other_id]:<20} familiarity {st.familiarity:.2f} valence {st.valence:+.2f} conv {st.conversations} seen {st.presence}"
        )
    m = network.measures(agents, network.current_states(sim.db), cfg.social.tie_threshold)
    print(f"  network: density {m['density']} edges {m['edge_count']} components {m['components']} reciprocity {m['reciprocity']}")
    at = datetime(2023, 2, 13, 10, 0)
    early = network.measures(agents, network.reconstruct(sim.db, at), cfg.social.tie_threshold)
    print(f"  rebuilt from the event log at {at:%H:%M}: edges {early['edge_count']} (records {early['records']})")

    section("Behavior from plans, events and frames")
    b = beh.behavior(sim.db, agents, start=cfg.scenario.start, end=sim.clock.now)
    for a, row in b["agents"].items():
        print(
            f"  {names[a]:<20} actions {row['actions']:>3} scheduled {row['scheduled_share']} adherence {row['plan_adherence']} replans {row['replans']} idle {row['idle_share']}"
        )
    print(f"  pooled: {json.dumps(b['pooled'])}")

    section("Belief ledger (evaluator side; never shown to agents)")
    sc = load_scenario(repo_path(cfg.scenario.path), population=POP)
    ledger = BeliefLedger(sim.db, load_topics(sc.events), agents, before=sim.clock.now)
    for topic, s in ledger.summary()["topics"].items():
        print(f"  {topic}: holders {[names[h] for h in s['holders']]}; grounded pairs {s['grounded_pairs']}; knowledge coverage {s['knowledge_coverage']}")
    for r in ledger.second_order("valentines_party"):
        if r["basis"]:
            print(
                f"    {names[r['agent_id']]} has grounds ({r['basis']}) to believe {names[r['about']]} knows; {names[r['about']]} really knows: {r['other_holds']}"
            )

    section("Planted-fact retrieval probe on the final snapshot, with and without forgetting")
    snap = base / "snapshots" / "final.sqlite"
    plain = mp.planted_facts(cfg, snap, agents, k=10)["summary"]
    harsh = RetrievalSettings.from_config(cfg.retrieval)
    harsh.forgetting = Forgetting(enabled=True, decay=0.5, threshold=-0.6, importance_bonus=0.1)
    forgetful = mp.planted_facts(cfg, snap, agents, k=10, settings=harsh)["summary"]
    print(f"  default   recall@10 {plain['recall_at_k']} by age {plain['by_age']} forgotten {plain['forgotten']}")
    print(f"  forgetting recall@10 {forgetful['recall_at_k']} by age {forgetful['by_age']} forgotten {forgetful['forgotten']}")
    sim.close()

    section("Counterfactual fork: a fire in Hobbs Cafe at 12:05, same past up to 12:00")
    fire = [
        {
            "kind": "ambient",
            "at": "2023-02-13T12:05:00",
            "id": "cafe_fire",
            "tile": [78, 19],
            "subject": "fire",
            "object": "burning",
            "description": "a fire is burning in Hobbs Cafe",
            "until": "2023-02-13T13:00:00",
        },
        {"kind": "object_state", "at": "2023-02-13T12:05:00", "address": "the Ville:Hobbs Cafe:cafe:cooking area", "state": "burning"},
    ]
    fork_dir = work / "fire"
    origin = fork_run(base, "2023-02-13T12-00-00", fork_dir, interventions=fire, label="fire fork (MOCK)")
    fork = Simulation(load_run_config(fork_dir), fork_dir)
    fork.run()
    print(f"  fork of {origin['run_id']} at {origin['sim_time']} → {fork.status} at {fork.clock.now}")
    t = datetime(2023, 2, 13, 12, 5)
    for label, db in (("control (source run)", Database(base / "state.sqlite", read_only=True)), ("fire fork", fork.db)):
        a = beh.adaptation(db, agents, t, ["fire", "burning", "smoke"], window_minutes=120)
        print(
            f"  {label:<22} perceived {len(a['perceived'])} changed plans {a['changed_share']} latency {a['median_latency_minutes']} min mentions {a['mentions_in_conversation']}"
        )
    fork.close()
    print(f"\nRun directories kept under {work}. Open one with: ga serve --run-dir {fork_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
