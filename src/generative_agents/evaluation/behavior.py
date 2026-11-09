"""Behavioral measures from a run's own records (research extension): plan adherence, reactivity, idleness.

Everything is computed from the ``plans``, ``events`` and ``frames`` tables of a finished run
or snapshot; no model is called and no interview is read. Per agent (and pooled):

* **scheduled share**: executed actions that came from the agent's own schedule (``generated``
  or ``block`` tasks) over all executed actions; the rest were reactions, waits, conversations
  or post-interruption replans;
* **plan adherence**: hour blocks (not superseded) during which at least one action was
  started from a task of that block, over all hour blocks that fell inside the simulated span;
* **superseded tasks**, **replans**, **reactions** by decision, **action failures**,
  **constraint refusals**, **plan failures**;
* **idle share**: frames in which the agent had no action (idle or failed) over all frames
  where it appears;
* **conversations** and utterances the agent took part in.

Adaptation measures (``adaptation``) take an intervention time and keywords and report, per
agent, the first replan or non-continue reaction after it, how many agents changed plans within
a window, and when the intervention was first mentioned in a conversation.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from ..db import Database, parse_iso

SCHEDULED_SOURCES = {"generated", "block"}


def _events(db: Database, types: tuple[str, ...]) -> list[dict[str, Any]]:
    marks = ",".join("?" for _ in types)
    out = []
    for r in db.query(f"SELECT id, step, sim_time, type, agent_id, json FROM events WHERE type IN ({marks}) ORDER BY id", types):
        d = json.loads(r["json"])
        d.update({"_id": r["id"], "step": r["step"], "sim_time": r["sim_time"], "type": r["type"], "agent_id": r["agent_id"]})
        out.append(d)
    return out


def _plans(db: Database) -> list[dict[str, Any]]:
    return [json.loads(r["json"]) for r in db.query("SELECT json FROM plans ORDER BY agent_id, start, id")]


def idle_share(db: Database, agents: list[str]) -> dict[str, float | None]:
    seen: Counter[str] = Counter()
    idle: Counter[str] = Counter()
    state: dict[str, list[Any]] = {}
    for r in db.query("SELECT step, json FROM frames ORDER BY step"):
        f = json.loads(r["json"])
        if f.get("key"):
            state = dict(f["agents"])
        else:
            state.update(f["agents"])
        for aid, v in state.items():
            seen[aid] += 1
            if v[3] in ("idle", "failed"):
                idle[aid] += 1
    return {a: (round(idle[a] / seen[a], 4) if seen[a] else None) for a in agents}


def behavior(db: Database, agents: list[str], *, start: datetime | None = None, end: datetime | None = None) -> dict[str, Any]:
    plans = _plans(db)
    events = _events(db, ("action", "replan", "reaction", "action_failure", "constraint", "plan_failure", "conversation"))
    sim_start = start or parse_iso(db.get_meta("scenario_start") or "") or min((parse_iso(p["created_at"]) for p in plans), default=None)
    sim_end = end or parse_iso(db.get_meta("sim_time") or "")
    by_id = {p["id"]: p for p in plans}
    per: dict[str, dict[str, Any]] = {}
    for aid in agents:
        acts = [e for e in events if e["type"] == "action" and e["agent_id"] == aid]
        sources = Counter((by_id.get(e.get("task") or "", {}).get("source") or "unknown") for e in acts)
        scheduled = sum(v for k, v in sources.items() if k in SCHEDULED_SOURCES)
        blocks = [p for p in plans if p["agent_id"] == aid and p["level"] == "hour" and p["status"] != "superseded"]
        if sim_end is not None:
            blocks = [
                b
                for b in blocks
                if parse_iso(b["start"]) < sim_end and (sim_start is None or parse_iso(b["start"]) + timedelta(minutes=b["duration_min"]) > sim_start)
            ]
        block_ids = {b["id"] for b in blocks}
        followed = {
            by_id[e["task"]]["parent_id"]
            for e in acts
            if e.get("task") in by_id and by_id[e["task"]].get("parent_id") in block_ids and by_id[e["task"]]["source"] in SCHEDULED_SOURCES
        }
        tasks = [p for p in plans if p["agent_id"] == aid and p["level"] == "task"]
        reactions = Counter(e.get("decision") for e in events if e["type"] == "reaction" and e["agent_id"] == aid)
        convs = [e for e in events if e["type"] == "conversation" and aid in (e.get("participants") or [])]
        per[aid] = {
            "actions": len(acts),
            "scheduled_actions": scheduled,
            "scheduled_share": round(scheduled / len(acts), 4) if acts else None,
            "action_sources": dict(sources),
            "hour_blocks": len(blocks),
            "blocks_followed": len(followed),
            "plan_adherence": round(len(followed) / len(blocks), 4) if blocks else None,
            "tasks": len(tasks),
            "superseded_tasks": sum(1 for t in tasks if t["status"] == "superseded"),
            "replans": sum(1 for e in events if e["type"] == "replan" and e["agent_id"] == aid),
            "reactions": dict(reactions),
            "reaction_decisions": sum(reactions.values()),
            "non_continue_reactions": sum(v for k, v in reactions.items() if k != "continue"),
            "action_failures": sum(1 for e in events if e["type"] == "action_failure" and e["agent_id"] == aid),
            "constraint_refusals": sum(1 for e in events if e["type"] == "constraint" and e["agent_id"] == aid),
            "plan_failures": sum(1 for e in events if e["type"] == "plan_failure" and e["agent_id"] == aid),
            "conversations": len(convs),
            "utterances": sum(int(e.get("utterances") or 0) for e in convs),
        }
    idle = idle_share(db, agents)
    for aid in agents:
        per[aid]["idle_share"] = idle.get(aid)

    def pooled(key: str, num: str | None = None, den: str | None = None) -> float | None:
        if num and den:
            n = sum(per[a][num] for a in agents)
            d = sum(per[a][den] for a in agents)
            return round(n / d, 4) if d else None
        vals = [per[a][key] for a in agents if per[a][key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "agents": per,
        "pooled": {
            "scheduled_share": pooled("", "scheduled_actions", "actions"),
            "plan_adherence": pooled("", "blocks_followed", "hour_blocks"),
            "idle_share": pooled("idle_share"),
            "replans_per_agent": round(sum(per[a]["replans"] for a in agents) / len(agents), 3) if agents else None,
            "reaction_rate": pooled("", "non_continue_reactions", "reaction_decisions"),
            "conversations_per_agent": round(sum(per[a]["conversations"] for a in agents) / len(agents), 3) if agents else None,
            "action_failures": sum(per[a]["action_failures"] for a in agents),
            "constraint_refusals": sum(per[a]["constraint_refusals"] for a in agents),
            "plan_failures": sum(per[a]["plan_failures"] for a in agents),
        },
        "span": {"start": sim_start.isoformat() if sim_start else None, "end": sim_end.isoformat() if sim_end else None},
    }


def adaptation(
    db: Database, agents: list[str], at: datetime, keywords: list[str], *, window_minutes: int = 120, exposed: list[str] | None = None
) -> dict[str, Any]:
    """How agents changed course after an intervention at ``at``.

    ``keywords`` (regexes) identify the intervention in reactions, inserted activities and
    utterances. ``exposed`` optionally restricts the "agents changed plans" rate to agents who
    perceived the event (from the ``reaction`` events whose observation matches), otherwise
    every agent counts.
    """

    end = at + timedelta(minutes=window_minutes)
    pat = re.compile("|".join(keywords), re.I) if keywords else None
    events = _events(db, ("replan", "reaction"))
    per: dict[str, dict[str, Any]] = {}
    for aid in agents:
        mine = [e for e in events if e["agent_id"] == aid and at <= parse_iso(e["sim_time"]) <= end]
        perceived = [e for e in mine if e["type"] == "reaction" and pat and pat.search(e.get("observation") or "")]
        reacted = [
            e
            for e in mine
            if e["type"] == "reaction"
            and e.get("decision") not in (None, "continue")
            and (not pat or pat.search((e.get("observation") or "") + " " + (e.get("new_activity") or "")))
        ]
        replans = [e for e in mine if e["type"] == "replan" and (not pat or pat.search(e.get("inserted") or ""))]
        first = min((parse_iso(e["sim_time"]) for e in reacted + replans), default=None)
        per[aid] = {
            "perceived": bool(perceived),
            "first_perceived_at": perceived[0]["sim_time"] if perceived else None,
            "reacted": bool(reacted),
            "replanned": bool(replans),
            "latency_minutes": round((first - at).total_seconds() / 60, 1) if first else None,
            "reactions_in_window": len([e for e in mine if e["type"] == "reaction"]),
            "replans_in_window": len([e for e in mine if e["type"] == "replan"]),
        }
    mentions = []
    for r in db.query("SELECT json FROM conversations ORDER BY started_at, id"):
        c = json.loads(r["json"])
        started = parse_iso(c["started_at"])
        if started is None or started < at or started > end:
            continue
        for u in c.get("utterances", []):
            if pat and pat.search(u["text"]):
                mentions.append({"time": u.get("sim_time") or c["started_at"], "speaker": u["speaker_id"], "conversation_id": c["id"], "text": u["text"]})
                break
    denom = [a for a in agents if (exposed is None or a in exposed)]
    changed = [a for a in denom if per[a]["reacted"] or per[a]["replanned"]]
    perceivers = [a for a in agents if per[a]["perceived"]]
    lat = [per[a]["latency_minutes"] for a in agents if per[a]["latency_minutes"] is not None]
    return {
        "at": at.isoformat(),
        "window_minutes": window_minutes,
        "keywords": keywords,
        "agents": per,
        "perceived": perceivers,
        "changed_plans": changed,
        "changed_share": round(len(changed) / len(denom), 3) if denom else None,
        "changed_share_among_perceivers": round(len([a for a in perceivers if a in changed]) / len(perceivers), 3) if perceivers else None,
        "median_latency_minutes": sorted(lat)[len(lat) // 2] if lat else None,
        "mentions_in_conversation": len(mentions),
        "first_mention": mentions[0] if mentions else None,
        "agents_mentioning": len({m["speaker"] for m in mentions}),
    }


def behavior_by_hour(db: Database, agents: list[str]) -> list[dict[str, Any]]:
    """Counts of actions, replans, reactions and conversations per simulated hour (for the dashboard)."""

    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for e in _events(db, ("action", "replan", "reaction", "conversation", "reflection", "intervention")):
        hour = e["sim_time"][:13]
        buckets[hour][e["type"]] += 1
        if e["type"] == "reaction" and e.get("decision") not in (None, "continue"):
            buckets[hour]["non_continue_reactions"] += 1
    return [{"hour": h + ":00", **dict(c)} for h, c in sorted(buckets.items())]
