"""Per-agent relationship records that evolve from observed interactions (research extension).

Each agent keeps one directed record per person it has interacted with. The record is the
agent's *own* social memory: it is built only from events the agent took part in or
perceived (its conversations, people it saw nearby, and its own appraisal of a
conversation), never from the other agent's state. Updates are fixed, interpretable rules
whose parameters live in ``config.SocialSection``:

* **familiarity** in [0, 1] rises with saturating gains, ``f += gain * (1 - f)``, for each
  conversation (``familiarity_gain_conversation``) and for co-presence in the same arena at
  most once per ``presence_cooldown_minutes`` (``familiarity_gain_presence``); it decays by
  ``decay_per_day`` per simulated day without contact, applied lazily at the next update;
* **valence** in [-1, 1] is an exponential moving average (rate ``valence_rate``) of the
  agent's appraisals of its conversations, scaled from the -2..2 rating; without appraisals it
  stays at zero.

Every update appends a row to ``relationship_events`` with the values before and after, so
the social network at any simulated time can be reconstructed exactly
(``social.network.reconstruct``). Records are never deleted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ..db import Database, iso, stable_json
from ..simulation.clock import long_time

FAMILIARITY_LABELS = ((0.6, "close"), (0.35, "familiar"), (0.12, "an acquaintance"), (0.0, "barely known"))
VALENCE_LABELS = ((0.5, "warm"), (0.15, "friendly"), (-0.15, "neutral"), (-0.5, "cool"), (-2.0, "strained"))


def familiarity_label(f: float) -> str:
    return next(label for cut, label in FAMILIARITY_LABELS if f >= cut)


def valence_label(v: float) -> str:
    return next(label for cut, label in VALENCE_LABELS if v >= cut)


class RelationshipState(BaseModel):
    agent_id: str
    other_id: str
    other_name: str = ""
    familiarity: float = 0.0
    valence: float = 0.0
    conversations: int = 0
    presence: int = 0
    appraisals: int = 0
    first_met_at: datetime | None = None
    last_interaction_at: datetime | None = None
    last_conversation_at: datetime | None = None
    last_presence_at: datetime | None = None
    last_conversation_id: str | None = None
    updated_at: datetime | None = None

    def is_tie(self, threshold: float) -> bool:
        return self.familiarity >= threshold


class RelationshipStore:
    """Identity map over ``relationships`` rows, flushed at commit like the other stores."""

    def __init__(self, db: Database, cfg: Any, step_getter: Callable[[], int | None] | None = None):
        self.db = db
        self.cfg = cfg
        self.step_getter = step_getter or (lambda: 0)
        self._live: dict[tuple[str, str], RelationshipState] = {}
        self._dirty: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------ persistence
    def get(self, agent_id: str, other_id: str, other_name: str = "") -> RelationshipState:
        key = (agent_id, other_id)
        if key not in self._live:
            row = self.db.one("SELECT json FROM relationships WHERE agent_id=? AND other_id=?", key)
            st = RelationshipState.model_validate_json(row["json"]) if row else RelationshipState(agent_id=agent_id, other_id=other_id, other_name=other_name)
            if other_name and not st.other_name:
                st.other_name = other_name
            self._live[key] = st
        return self._live[key]

    def peek(self, agent_id: str, other_id: str) -> RelationshipState | None:
        """The record if it exists (committed or live); never creates one."""

        key = (agent_id, other_id)
        if key in self._live:
            return self._live[key]
        row = self.db.one("SELECT json FROM relationships WHERE agent_id=? AND other_id=?", key)
        return RelationshipState.model_validate_json(row["json"]) if row else None

    def for_agent(self, agent_id: str) -> list[RelationshipState]:
        rows = {
            r["other_id"]: RelationshipState.model_validate_json(r["json"])
            for r in self.db.query("SELECT other_id, json FROM relationships WHERE agent_id=?", (agent_id,))
        }
        for (a, b), st in self._live.items():
            if a == agent_id:
                rows[b] = st
        return sorted(rows.values(), key=lambda s: s.other_id)

    def all(self) -> list[RelationshipState]:
        rows = {
            (r["agent_id"], r["other_id"]): RelationshipState.model_validate_json(r["json"])
            for r in self.db.query("SELECT agent_id, other_id, json FROM relationships")
        }
        rows.update(self._live)
        return [rows[k] for k in sorted(rows)]

    def flush(self) -> None:
        for key in sorted(self._dirty):
            st = self._live[key]
            self.db.execute(
                "INSERT INTO relationships(agent_id, other_id, json) VALUES(?,?,?) ON CONFLICT(agent_id, other_id) DO UPDATE SET json=excluded.json",
                (key[0], key[1], st.model_dump_json()),
            )
        self._dirty.clear()

    def invalidate(self) -> None:
        self._live.clear()
        self._dirty.clear()

    def _log(self, st: RelationshipState, kind: str, now: datetime, before: dict[str, float], **extra: Any) -> None:
        self.db.execute(
            "INSERT INTO relationship_events(step, sim_time, agent_id, other_id, kind, json) VALUES(?,?,?,?,?,?)",
            (
                int(self.step_getter() or 0),
                iso(now),
                st.agent_id,
                st.other_id,
                kind,
                stable_json({"before": before, "after": {"familiarity": st.familiarity, "valence": st.valence}, **extra}),
            ),
        )

    # ------------------------------------------------------------------ update rules
    def _touch(self, st: RelationshipState, now: datetime) -> dict[str, float]:
        """Apply lazy decay since the last update; returns the values before this update."""

        before = {"familiarity": st.familiarity, "valence": st.valence}
        if st.updated_at is not None and now > st.updated_at and self.cfg.decay_per_day > 0:
            days = (now - st.updated_at).total_seconds() / 86400.0
            st.familiarity *= (1.0 - self.cfg.decay_per_day) ** days
        if st.first_met_at is None:
            st.first_met_at = now
        st.updated_at = now
        self._dirty.add((st.agent_id, st.other_id))
        return before

    @staticmethod
    def _gain(f: float, gain: float) -> float:
        return min(1.0, f + gain * (1.0 - f))

    def record_conversation(
        self, agent_id: str, other_id: str, other_name: str, now: datetime, *, conversation_id: str, appraisal: int | None
    ) -> RelationshipState:
        """One side of a conversation: familiarity gain and, with an appraisal, a valence update."""

        st = self.get(agent_id, other_id, other_name)
        before = self._touch(st, now)
        st.familiarity = self._gain(st.familiarity, self.cfg.familiarity_gain_conversation)
        st.conversations += 1
        st.last_interaction_at = st.last_conversation_at = now
        st.last_conversation_id = conversation_id
        if appraisal is not None:
            target = max(-1.0, min(1.0, appraisal / 2.0))
            st.valence = st.valence + self.cfg.valence_rate * (target - st.valence)
            st.appraisals += 1
        self._log(st, "conversation", now, before, conversation_id=conversation_id, appraisal=appraisal)
        return st

    def record_presence(self, agent_id: str, other_id: str, other_name: str, now: datetime) -> bool:
        """Seeing someone nearby: a small familiarity gain at most once per cooldown. Returns whether it counted."""

        st = self.get(agent_id, other_id, other_name)
        if st.last_presence_at is not None and (now - st.last_presence_at).total_seconds() < self.cfg.presence_cooldown_minutes * 60:
            return False
        before = self._touch(st, now)
        st.familiarity = self._gain(st.familiarity, self.cfg.familiarity_gain_presence)
        st.presence += 1
        st.last_presence_at = st.last_interaction_at = now
        self._log(st, "presence", now, before)
        return True

    # ------------------------------------------------------------------ agent-visible text
    def describe(self, agent_id: str, other_id: str, now: datetime, agent_name: str, other_name: str) -> str:
        """The agent's own relationship record as one or two sentences for its prompts."""

        st = self.peek(agent_id, other_id)
        first = other_name.split()[0]
        if st is None or (st.conversations == 0 and st.presence == 0):
            return f"{agent_name} has no record of interacting with {other_name}."
        parts = [f"{agent_name}'s record of {other_name}: {familiarity_label(st.familiarity)}"]
        if st.conversations:
            when = f" (last {long_time(st.last_conversation_at)})" if st.last_conversation_at else ""
            parts.append(f"{st.conversations} conversation{'s' if st.conversations != 1 else ''}{when}")
        if st.presence:
            parts.append(f"seen nearby {st.presence} time{'s' if st.presence != 1 else ''}")
        text = "; ".join(parts) + "."
        if st.appraisals:
            text += f" {agent_name} feels {valence_label(st.valence)} toward {first}."
        return text
