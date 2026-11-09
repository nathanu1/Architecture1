"""Wiring of social memory into a run: appraisal calls, presence hooks and prompt text."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..cognition.services import Services
from ..providers.base import TaskFailed
from ..schemas import AgentIdentity, Conversation
from .relationships import RelationshipStore


class SocialMemory:
    """One instance per run. All writes go through the store; appraisal calls through the gateway."""

    def __init__(self, svc: Services, store: RelationshipStore):
        self.svc = svc
        self.store = store
        self.cfg = svc.cfg.social

    @property
    def informs_prompts(self) -> bool:
        return bool(self.cfg.inform_prompts)

    # ------------------------------------------------------------------ events the agent took part in
    def after_conversation(self, conv: Conversation, a: AgentIdentity, b: AgentIdentity, transcript: str, now: datetime) -> dict[str, int | None]:
        """Update both participants' records after a conversation with utterances.

        Each side's appraisal is its own model call over the shared transcript (when
        ``social.appraisal`` is ``llm``); a failed call leaves that side's valence unchanged and
        is logged, never replaced by an invented rating.
        """

        appraisals: dict[str, int | None] = {}
        for me, other in ((a, b), (b, a)):
            score: int | None = None
            if self.cfg.appraisal == "llm" and conv.utterances:
                try:
                    out = self.svc.gateway.run(
                        "conversation_appraisal",
                        {
                            "agent_name": me.name,
                            "partner_name": other.name,
                            "transcript": transcript,
                            "_transcript_text": transcript,
                            "_name": me.name,
                            "_partner": other.name,
                        },
                        agent_id=me.id,
                        sim_time=now,
                        purpose="social:appraisal",
                    )
                    score = int(out.output.valence)
                except TaskFailed as exc:
                    self.svc.events.log("appraisal_failure", now, me.id, conversation_id=conv.id, error=str(exc))
            appraisals[me.id] = score
            self.store.record_conversation(me.id, other.id, other.name, now, conversation_id=conv.id, appraisal=score)
        return appraisals

    def on_presence(self, agent_id: str, other_id: str, other_name: str, now: datetime) -> bool:
        return self.store.record_presence(agent_id, other_id, other_name, now)

    # ------------------------------------------------------------------ agent-visible text
    def context_line(self, me: AgentIdentity, other_id: str, other_name: str, now: datetime) -> str:
        return self.store.describe(me.id, other_id, now, me.name, other_name)

    # ------------------------------------------------------------------ lifecycle
    def flush(self) -> None:
        self.store.flush()

    def invalidate(self) -> None:
        self.store.invalidate()

    def manifest(self) -> dict[str, Any]:
        return {"track": self.cfg.track, "appraisal": self.cfg.appraisal, "inform_prompts": self.cfg.inform_prompts, "tie_threshold": self.cfg.tie_threshold}
