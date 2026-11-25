"""What each fork of a fire experiment recorded, in the agents' own words (no scoring).

The adaptation metric counts perceivers, changes of plan and latencies. With a real model
the counts leave out what matters most: what the resident decided to do, whether she kept
at it while the fire burned, how important she rated the memory, and what she says when
asked afterwards. This script prints those records for every run of an experiment and
writes them to ``fire_report.json``. With ``--ask`` it also interviews one agent on each
run's final snapshot (one model call per run, recorded in that run's ledger).

    uv run python examples/round2_fire_report.py runs/experiments/fire_llama32 \
        --at 2023-02-13T09:10:00 --agent isabella_rodriguez \
        --ask "Did anything unusual happen at Hobbs Cafe this morning?"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from generative_agents.db import Database  # noqa: E402
from generative_agents.evaluation.experiment import load_rows  # noqa: E402
from generative_agents.evaluation.interview import InterviewSession  # noqa: E402
from generative_agents.memory.masks import FULL  # noqa: E402
from generative_agents.simulation.engine import load_run_config  # noqa: E402

KEYWORDS = re.compile(r"fire|burning|smoke|flame", re.I)


def run_report(run_dir: Path, at: str, agent: str | None) -> dict:
    db = Database(run_dir / "state.sqlite", read_only=True)
    try:
        events = [
            {"sim_time": r["sim_time"], "type": r["type"], "agent_id": r["agent_id"], **json.loads(r["json"])}
            for r in db.query("SELECT * FROM events WHERE sim_time >= ? ORDER BY id", (at,))
        ]
        memories = [
            dict(r)
            for r in db.query(
                "SELECT owner_id, kind, origin, importance, created_at, description FROM memories WHERE created_at >= ? ORDER BY created_at, seq", (at,)
            )
        ]
        conversations = [json.loads(r["json"]) for r in db.query("SELECT json FROM conversations WHERE started_at >= ? ORDER BY started_at", (at,))]
    finally:
        db.close()
    reactions = [e for e in events if e["type"] == "reaction" and KEYWORDS.search(e.get("observation") or "")]
    out = {
        "fire_reactions": [
            {
                "time": e["sim_time"][11:16],
                "agent": e["agent_id"],
                "decision": e.get("decision"),
                "new_activity": e.get("new_activity"),
                "minutes": e.get("minutes"),
                "reason": e.get("reason"),
            }
            for e in reactions
        ],
        "all_reaction_decisions": {},
        "fire_memories": [
            {
                "time": m["created_at"][11:16],
                "owner": m["owner_id"],
                "kind": m["kind"],
                "origin": m["origin"],
                "importance": m["importance"],
                "text": m["description"],
            }
            for m in memories
            if KEYWORDS.search(m["description"])
        ],
        "conversations": [
            {
                "start": c["started_at"][11:16],
                "participants": c["participants"],
                "mentions_fire": any(KEYWORDS.search(u["text"]) for u in c.get("utterances", [])),
            }
            for c in conversations
        ],
        "failures": [
            {"time": e["sim_time"][11:16], "type": e["type"], "agent": e["agent_id"], "error": str(e.get("error"))[:160]}
            for e in events
            if e["type"].endswith("failure")
        ],
    }
    for e in events:
        if e["type"] == "reaction":
            out["all_reaction_decisions"][e.get("decision") or "none"] = out["all_reaction_decisions"].get(e.get("decision") or "none", 0) + 1
    if agent:
        acts = [e for e in events if e["agent_id"] == agent and e["type"] == "action"]
        out["actions"] = [{"time": e["sim_time"][11:16], "activity": e.get("activity"), "address": (e.get("address") or "").split(":", 1)[-1]} for e in acts]
        about = [a for a in out["actions"] if KEYWORDS.search(a["activity"] or "")]
        out["actions_about_the_fire"] = len(about)
        out["actions_total"] = len(acts)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("experiment_dir")
    ap.add_argument("--at", required=True, help="start of the intervention (ISO time)")
    ap.add_argument("--agent", help="print this agent's actions after the intervention")
    ap.add_argument("--ask", help="interview --agent with this question on every run's final snapshot (one model call per run)")
    args = ap.parse_args()
    root = Path(args.experiment_dir)
    report = {}
    for row in load_rows(root):
        if row.get("status") != "completed":
            continue
        run_dir = Path(row["run_dir"])
        rep = run_report(run_dir, args.at, args.agent)
        if args.ask and args.agent:
            session = InterviewSession(
                load_run_config(run_dir),
                run_dir / "snapshots" / "final.sqlite",
                ledger_path=run_dir / "provider.sqlite",
                scope=f"{run_dir.name}::fire-report",
                mask=FULL,
            )
            try:
                answer = session.ask(args.agent, args.ask)
                rep["interview"] = {
                    "question": args.ask,
                    "answer": answer.answer,
                    "mentions_fire": bool(KEYWORDS.search(answer.answer)),
                    "retrieved": len(answer.retrieved_ids),
                }
            finally:
                session.close()
        report[row["run_id"]] = rep
        print(f"\n=== {row['run_id']}")
        shown = [r for r in rep["fire_reactions"] if r["decision"] != "continue"][:12]
        print(
            f"  {len(rep['fire_reactions'])} reaction decisions about a fire-related observation, {sum(1 for r in rep['fire_reactions'] if r['decision'] != 'continue')} of them not 'continue'"
        )
        for r in shown:
            print(f"  {r['time']} {r['agent']}: {r['decision']} -> {r['new_activity']!r} ({r['minutes']} min); reason: {r['reason']}")
        print(f"  reaction decisions of all kinds: {rep['all_reaction_decisions']}")
        for m in rep["fire_memories"][:8]:
            print(f"  memory {m['time']} {m['owner']} [{m['origin']}, importance {m['importance']}]: {m['text']}")
        if args.agent:
            print(f"  {args.agent}: {rep['actions_about_the_fire']} of {rep['actions_total']} actions after {args.at[11:16]} mention the fire")
            for a in rep["actions"][:14]:
                print(f"    {a['time']} {a['activity']} @ {a['address']}")
        print(
            f"  conversations: {len(rep['conversations'])}, mentioning the fire: {sum(c['mentions_fire'] for c in rep['conversations'])}; failures: {len(rep['failures'])}"
        )
        if "interview" in rep:
            print(f"  Q: {args.ask}\n  A: {rep['interview']['answer']}")
    (root / "fire_report.json").write_text(json.dumps(report, indent=2))
    print(f"\nwrote {root / 'fire_report.json'}")


if __name__ == "__main__":
    main()
