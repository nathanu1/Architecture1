"""Belief ledger: what each agent has grounds to believe, kept apart from world truth (research extension).

The engine already enforces partial observability: an agent's prompts see only its own
memory stream. This module makes the resulting *epistemic state* measurable without adding
any new channel of information to agents. For each evaluator topic (``events.yaml``) and each
agent it records, from the agent's own memories:

* **first-order beliefs**: the exposures that let the agent know of the topic (seed,
  statement heard, inner voice, direct observation), with provenance (time, origin, speaker)
  and the detail values each exposure carried (date, time, place, ...), including *variants*
  when different sources gave different surface values for the same detail;
* **second-order grounds**: for every other agent B, whether A has a basis to believe B knows
  (A told B about it, or A heard B mention it), with the time of the first such ground.

**Truth** is the evaluator's view: B "knows" when B's own memory holds a supported exposure.
Comparing A's grounds with B's truth gives the Theory-of-Mind table that ``evaluation.tom``
also uses for interview probes. Everything here reads finished run data (or a snapshot) and
is never rendered into a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..db import Database, parse_iso
from ..evaluation.evidence import Topic, topic_evidence
from ..schemas import MemoryOrigin

NORMALIZE = re.compile(r"[^a-z0-9]+")


def detail_values(topic: Topic, text: str) -> dict[str, str]:
    """For each detail category the text states, the normalized surface value it used."""

    out: dict[str, str] = {}
    for detail, patterns in topic.details.items():
        for p in patterns:
            m = re.search(p, text, re.I)
            if m:
                out[detail] = NORMALIZE.sub(" ", m.group(0).lower()).strip()
                break
    return out


@dataclass
class Exposure:
    memory_id: str
    at: str
    origin: str
    speaker_id: str | None
    conversation_id: str | None
    details: dict[str, str]
    text: str


@dataclass
class Ground:
    """Why A can believe B knows: A told B, or A heard B say it."""

    other_id: str
    basis: str  # told | heard | both
    first_at: str
    memory_ids: list[str] = field(default_factory=list)


@dataclass
class AgentBeliefs:
    agent_id: str
    topic: str
    exposures: list[Exposure] = field(default_factory=list)
    grounds: dict[str, Ground] = field(default_factory=dict)

    @property
    def holds(self) -> bool:
        return bool(self.exposures)

    @property
    def first_exposure_at(self) -> str | None:
        return self.exposures[0].at if self.exposures else None

    @property
    def sources(self) -> list[str]:
        return sorted({e.speaker_id for e in self.exposures if e.speaker_id})

    def detail_variants(self) -> dict[str, dict[str, list[str]]]:
        """detail -> surface value -> memory ids (more than one value is a variant to review)."""

        out: dict[str, dict[str, list[str]]] = {}
        for e in self.exposures:
            for d, v in e.details.items():
                out.setdefault(d, {}).setdefault(v, []).append(e.memory_id)
        return out

    def conflicting_details(self) -> list[str]:
        return sorted(d for d, vals in self.detail_variants().items() if len(vals) > 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "topic": self.topic,
            "holds": self.holds,
            "first_exposure_at": self.first_exposure_at,
            "sources": self.sources,
            "exposures": [e.__dict__ for e in self.exposures],
            "detail_variants": self.detail_variants(),
            "conflicting_details": self.conflicting_details(),
            "grounds": {k: g.__dict__ for k, g in sorted(self.grounds.items())},
        }


def _conversation_partners(db: Database) -> dict[str, list[str]]:
    out = {}
    for r in db.query("SELECT id, participants FROM conversations"):
        out[r["id"]] = r["participants"].split(",")
    return out


def agent_beliefs(db: Database, agent_id: str, topic: Topic, *, before: datetime | None = None, partners: dict[str, list[str]] | None = None) -> AgentBeliefs:
    partners = partners if partners is not None else _conversation_partners(db)
    out = AgentBeliefs(agent_id, topic.key)
    for e in topic_evidence(db, agent_id, topic, before=before):
        if not e["strong"]:
            continue
        out.exposures.append(
            Exposure(e["memory_id"], e["created_at"], e["origin"], e["speaker_id"], e["conversation_id"], detail_values(topic, e["text"]), e["text"])
        )
    # second-order grounds from the agent's own records of what was said in its conversations
    rows = db.query(
        "SELECT id, origin, description, created_at, speaker_id, conversation_id FROM memories WHERE owner_id=? AND origin IN (?, ?) ORDER BY seq",
        (agent_id, MemoryOrigin.OWN_STATEMENT.value, MemoryOrigin.STATEMENT.value),
    )
    for r in rows:
        created = parse_iso(r["created_at"])
        if before is not None and created is not None and created > before:
            continue
        if not topic.matches(r["description"]):
            continue
        others = [p for p in partners.get(r["conversation_id"] or "", []) if p != agent_id]
        if r["origin"] == MemoryOrigin.OWN_STATEMENT.value:
            basis = "told"
        else:
            basis = "heard"
            others = [r["speaker_id"]] if r["speaker_id"] else others
        for other in others:
            g = out.grounds.get(other)
            if g is None:
                out.grounds[other] = Ground(other, basis, r["created_at"], [r["id"]])
            else:
                g.memory_ids.append(r["id"])
                if g.basis != basis:
                    g.basis = "both"
    return out


class BeliefLedger:
    """Beliefs of every agent about every topic at one reference time."""

    def __init__(self, db: Database, topics: dict[str, Topic], agents: list[str], *, before: datetime | None = None):
        self.topics = topics
        self.agents = list(agents)
        self.before = before
        partners = _conversation_partners(db)
        self.beliefs: dict[str, dict[str, AgentBeliefs]] = {
            key: {a: agent_beliefs(db, a, t, before=before, partners=partners) for a in agents} for key, t in topics.items()
        }

    def truth(self, topic: str) -> dict[str, bool]:
        return {a: b.holds for a, b in self.beliefs[topic].items()}

    def second_order(self, topic: str) -> list[dict[str, Any]]:
        """For every ordered pair: A's grounds about B against B's actual (memory-supported) knowledge."""

        truth = self.truth(topic)
        rows = []
        for a in self.agents:
            for b in self.agents:
                if a == b:
                    continue
                g = self.beliefs[topic][a].grounds.get(b)
                if g is not None and truth[b]:
                    status = "grounded_true"  # A has grounds and B does know
                elif g is not None:
                    status = "grounded_unsupported"  # B spoke of it without a received memory
                elif truth[b]:
                    status = "no_grounds_true"  # B knows but nothing A experienced shows it
                else:
                    status = "no_grounds_false"
                rows.append(
                    {
                        "agent_id": a,
                        "about": b,
                        "basis": g.basis if g else None,
                        "first_at": g.first_at if g else None,
                        "other_holds": truth[b],
                        "status": status,
                    }
                )
        return rows

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"reference_time": self.before.isoformat() if self.before else None, "topics": {}}
        for key in self.topics:
            per = self.beliefs[key]
            second = self.second_order(key)
            holders = [a for a, b in per.items() if b.holds]
            grounded = [r for r in second if r["basis"]]
            coverage_den = [r for r in second if r["other_holds"]]
            out["topics"][key] = {
                "holders": holders,
                "holders_pct": round(100 * len(holders) / len(self.agents), 1) if self.agents else None,
                "with_conflicting_details": [a for a, b in per.items() if b.conflicting_details()],
                "mean_sources_per_holder": round(sum(len(per[a].sources) for a in holders) / len(holders), 2) if holders else None,
                "grounded_pairs": len(grounded),
                "grounded_true": len([r for r in second if r["status"] == "grounded_true"]),
                "grounded_unsupported": len([r for r in second if r["status"] == "grounded_unsupported"]),
                # of the pairs where B really knows, how many A has grounds for: social knowledge coverage
                "knowledge_coverage": round(len([r for r in coverage_den if r["basis"]]) / len(coverage_den), 3) if coverage_den else None,
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "beliefs": {k: {a: b.to_dict() for a, b in per.items()} for k, per in self.beliefs.items()},
            "second_order": {k: self.second_order(k) for k in self.topics},
        }


def load_ledger(db_path: str, topics: dict[str, Topic], agents: list[str], before: datetime | None = None) -> BeliefLedger:
    db = Database(db_path, read_only=True)
    try:
        return BeliefLedger(db, topics, agents, before=before)
    finally:
        db.close()


__all__ = ["BeliefLedger", "AgentBeliefs", "Exposure", "Ground", "agent_beliefs", "detail_values", "load_ledger"]
