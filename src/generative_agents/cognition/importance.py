"""Importance (poignancy) scoring at memory creation (paper §4.1 p. 9; spec D-1 … D-5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from ..schemas import AgentIdentity
from .context import identity_block

# (mundane examples, poignant examples, label, title)
ANCHORS: dict[str, tuple[str, str, str, str]] = {
    # paper p. 9 (and released poignancy_event_v1.txt)
    "observation": ("brushing teeth, making bed", "a break up, college acceptance", "piece of memory", "Memory"),
    # released poignancy_chat_v1.txt
    "conversation": ("routine morning greetings", "a conversation about breaking up, a fight", "conversation", "Conversation"),
    # released poignancy_thought_v1.txt (used for reflections and plans)
    "thought": ("I need to do the dishes, I need to walk the dog", "I wish to become a professor, I love Elie", "thought", "Thought"),
}


PLURALS = {"piece of memory": "memories", "conversation": "conversation statements", "thought": "thoughts"}

# The 1-10 range the output models validate, restated for grammar-constrained decoding.
RATING = {"rating": {"minimum": 1, "maximum": 10}}


def is_idle_text(text: str) -> bool:
    return text.rstrip(". ").endswith("is idle")


class ImportanceScorer:
    def __init__(self, gateway: Any, *, idle_shortcut: bool = True, batch_statements: bool = True):
        self.gateway = gateway
        self.idle_shortcut = idle_shortcut
        self.batch_statements = batch_statements

    def score(self, identity: AgentIdentity, text: str, kind: str, now: datetime, purpose: str | None = None) -> int:
        if self.idle_shortcut and is_idle_text(text):
            return 1  # released perceive.py:15-17
        mundane, poignant, label, title = ANCHORS[kind]
        result = self.gateway.run(
            "importance",
            {
                "agent_name": identity.name,
                "agent_summary": identity_block(identity, now),
                "mundane_examples": mundane,
                "poignant_examples": poignant,
                "kind_label": label,
                "kind_title": title,
                "memory": text,
                "_memory": text,
                "_kind": kind,
            },
            agent_id=identity.id,
            sim_time=now,
            purpose=purpose or f"importance:{kind}",
            constraints=RATING,
        )
        return int(result.output.rating)

    def score_batch(self, identity: AgentIdentity, texts: list[str], now: datetime, purpose: str | None = None, kind: str = "conversation") -> list[int]:
        """One call for the statements of one conversation or the items of one plan (spec D-5)."""

        if not texts:
            return []
        if self.idle_shortcut and all(is_idle_text(t) for t in texts):
            return [1] * len(texts)
        if not self.batch_statements:
            return [self.score(identity, t, kind, now, purpose) for t in texts]
        mundane, poignant, label, _title = ANCHORS[kind]
        items = [(str(i), t) for i, t in enumerate(texts, start=1)]
        expected = {i for i, _ in items}

        def validate(out: Any) -> list[str]:
            got = [r.id for r in out.ratings]
            errs = []
            if set(got) != expected or len(got) != len(expected):
                errs.append(f"need exactly one rating for each id {sorted(expected, key=int)}; got {got}")
            return errs

        result = self.gateway.run(
            "importance_batch",
            {
                "agent_name": identity.name,
                "agent_summary": identity_block(identity, now),
                "mundane_examples": mundane,
                "poignant_examples": poignant,
                "kind_label_plural": PLURALS.get(label, label + "s"),
                "numbered_memories": "\n".join(f"{i}. {t}" for i, t in items),
                "_items": items,
                "_kind": kind,
            },
            agent_id=identity.id,
            sim_time=now,
            purpose=purpose or f"importance:batch:{kind}",
            validate=validate,
            constraints={
                "ratings": {"minItems": len(items), "maxItems": len(items)},
                "ratings.*.id": {"enum": [i for i, _ in items]},
                "ratings.*.rating": RATING["rating"],
            },
        )
        by_id = {r.id: r.rating for r in result.output.ratings}
        return [int(by_id[i]) for i, _ in items]


# Everyday and momentous things, in the spirit of the paper's own examples (p. 9). A memory's
# rating is read from which of the two groups its meaning sits closer to.
EVERYDAY = (
    "brushing teeth",
    "making the bed",
    "doing the dishes",
    "walking the dog",
    "a routine greeting or goodbye",
    "getting dressed",
    "eating a meal",
    "an object sitting idle or in ordinary use",
    "tidying up the room",
    "walking down the street",
    "checking email and messages",
    "cooking a meal",
    "running errands and shopping",
    "ordinary tasks at work",
    "small talk about the weather",
    "sleeping or resting",
)
MOMENTOUS = (
    "a break up",
    "a college acceptance",
    "a death in the family",
    "falling in love",
    "a wedding",
    "losing a job",
    "a fight with a close friend",
    "a lifelong dream",
    "an invitation to a special occasion",
    "an emergency",
    "running for office",
    "a betrayal or a lie discovered",
    "a crime such as a robbery",
    "winning an award or a prize",
    "a serious illness or accident",
    "a big life decision such as moving away",
)


class MeaningImportance:
    """Importance without a model question (``importance.strategy: meaning``; deviation class X).

    The memory is embedded anyway to be stored. Its rating is how far its vector leans from
    the everyday examples toward the momentous ones: the mean cosine similarity to one group
    minus the mean to the other. The scale calibrates itself on the examples: a typical
    everyday example (left out of its own group) reads 1 and a typical momentous one reads 8,
    so the same code serves any embedding model. Checked against hand ratings in docs/tab.md.
    """

    def __init__(self, embeddings: Any, *, idle_shortcut: bool = True):
        self.embeddings = embeddings
        self.idle_shortcut = idle_shortcut
        self._scale: tuple[np.ndarray, np.ndarray, float, float] | None = None

    @staticmethod
    def _lean(x: np.ndarray, everyday: np.ndarray, momentous: np.ndarray) -> np.ndarray:
        x = x.astype(np.float64)
        return (x @ momentous.T).mean(axis=1) - (x @ everyday.T).mean(axis=1)

    def _calibrated(self) -> tuple[np.ndarray, np.ndarray, float, float]:
        if self._scale is not None:
            return self._scale
        both = self.embeddings.embed([*EVERYDAY, *MOMENTOUS]).astype(np.float64)
        both /= np.maximum(np.linalg.norm(both, axis=1, keepdims=True), 1e-12)
        ev, mo = both[: len(EVERYDAY)], both[len(EVERYDAY) :]
        low = float(np.mean([self._lean(ev[i : i + 1], np.delete(ev, i, axis=0), mo)[0] for i in range(len(ev))]))
        high = float(np.mean([self._lean(mo[i : i + 1], ev, np.delete(mo, i, axis=0))[0] for i in range(len(mo))]))
        if high - low < 1e-6:
            high = low + 1e-6  # vectors that tell nothing apart: everything reads as everyday
        scale = (ev, mo, low, high)
        if not getattr(self.embeddings, "provisional", False):
            self._scale = scale  # stand-in vectors (a browser pass still waiting for its model) are never kept
        return scale

    def rate(self, texts: list[str]) -> list[int]:
        ev, mo, low, high = self._calibrated()
        x = self.embeddings.embed(texts).astype(np.float64)
        x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
        lean = self._lean(x, ev, mo)
        return [int(v) for v in np.clip(np.rint(1 + (lean - low) / (high - low) * 7), 1, 10)]

    def score(self, identity: AgentIdentity, text: str, kind: str, now: datetime, purpose: str | None = None) -> int:
        if self.idle_shortcut and is_idle_text(text):
            return 1
        return self.rate([text])[0]

    def score_batch(self, identity: AgentIdentity, texts: list[str], now: datetime, purpose: str | None = None, kind: str = "conversation") -> list[int]:
        if not texts:
            return []
        idle = [self.idle_shortcut and is_idle_text(t) for t in texts]
        rated = iter(self.rate([t for t, i in zip(texts, idle, strict=True) if not i]) if not all(idle) else [])
        return [1 if i else next(rated) for i in idle]
