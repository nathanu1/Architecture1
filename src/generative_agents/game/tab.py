"""A town that lives inside a browser tab: no server, no threads, the model next to it in the page.

``TabTown`` is the whole back end of the town for one visitor. The page loads this package into
Pyodide (CPython compiled to WebAssembly), creates a ``TabTown`` and drives it from JavaScript:

* ``call(method, args_json)`` answers what the interface would otherwise fetch over HTTP: the
  town's ``info`` and ``map``, ``poll``, the player's ``action``\\ s and ``control``\\ s, a
  ``resident``, an ``object``, and the research inspector's ``research`` paths;
* ``tick()`` runs one pass of the town (``GameSession.iterate``) and says how long to wait before
  the next, or returns the question the residents need answered (``{"need": ...}``) when the
  model has to think. The page asks its in-browser model, calls ``deliver`` and ticks again.

The pause-for-an-answer works without threads because the engine's steps are transactions: the
unanswered step is rolled back and run again once the answer is known (``providers/deferred.py``).
The town commits after every step, so only the step in progress is ever repeated.

Nothing here knows about JavaScript, so the same class runs under CPython in the tests.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..config import GAConfig, load_config
from ..db import Database
from ..providers.deferred import Deferred, DeferredEmbedding, DeferredLLM
from ..providers.mock import MockLLM
from ..simulation.engine import load_run_config, save_config
from ..viewer.routes import NotFound, dispatch
from .payloads import object_info, resident_detail, town_info, town_map
from .session import GameSession

CONFIG = "configs/town_tab.yaml"
SCRIPTED = "scripted"


# How much of a resident's mind is the model (the page's `?depth=`):
# * "mind" (the default): the model plans each day, decides what to do, where, and what to say;
#   only a memory's importance is read from its meaning instead of asked (when the town has an
#   embedding model), residents plan as they wake, and a resident who has lived nothing yet is
#   not asked to summarise it;
# * "full": the paper's procedure to the letter: the model also rates every memory, everyone
#   plans at once, summaries are always written. The slowest;
# * "words": the model writes what a visitor reads (conversations, replies, reactions,
#   reflections) and the routine below comes from the scripted fixture. The fastest.
ROUTINE_TASKS = (
    "day_plan",
    "hourly_schedule",
    "decompose",
    "replan",
    "choose_location",
    "action_grounding",
    "importance",
    "importance_batch",
    "summary_aspect",
)
DEPTHS = ("mind", "full", "words")

# The embedding model the page runs for memory by meaning (its id in the in-browser runtime),
# and the instruction its authors prescribe in front of a retrieval query.
EMBED_MODEL = "snowflake-arctic-embed-s-q0f32-MLC-b4"
EMBED_DIMS = 384
EMBED_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def mind_overrides(mind: str | None, depth: str = "mind") -> list[str]:
    """Config overrides for the residents' mind: ``scripted`` (the offline fixture) or a model id
    that the page's in-browser model runtime will serve."""

    if not mind or mind == SCRIPTED:
        return ["providers.llm.kind=mock", "providers.llm.model=mock-llm-v1"]
    if depth not in DEPTHS:
        raise ValueError(f"depth must be one of {', '.join(DEPTHS)}")
    sets = ["providers.llm.kind=browser", f"providers.llm.model={json.dumps(mind)}"]
    if depth == "words":
        sets += ["providers.llm.pools.routine.kind=mock", "providers.llm.pools.routine.model=mock-llm-v1"]
        sets += [f"providers.llm.task_overrides.{task}.provider=routine" for task in ROUTINE_TASKS]
    sets += [f"importance.strategy={'meaning' if depth == 'mind' else 'llm'}"]
    if depth == "full":
        sets += ["planning.at_waking=false", "summary.min_lived=0", "summary.refresh_every_minutes=180"]
    return sets


def memory_overrides(memory: str) -> list[str]:
    """How a new town's residents search their memory: by ``meaning`` (the page's embedding
    model) or by shared ``words`` (the lexical fixture). Fixed when the town is founded: the
    vectors in its store belong to one model."""

    if memory != "meaning":
        return []
    return [
        "providers.embeddings.kind=browser",
        f"providers.embeddings.model={EMBED_MODEL}",
        f"providers.embeddings.dims={EMBED_DIMS}",
        f"providers.embeddings.query_prefix={json.dumps(EMBED_QUERY_PREFIX)}",
    ]


def cast_overrides(residents: int | None) -> list[str]:
    """Who lives in the town: the three of the small scenario, or that many of Smallville's 25."""

    if not residents or residents <= 3:
        return []
    from ..founding import BASE, choose_cast

    return [f"scenario.path={BASE}/scenario.yaml", f"scenario.population=[{', '.join(choose_cast(min(int(residents), 25)))}]"]


def first_waking(cfg: GAConfig) -> str | None:
    """The moment the town's earliest riser wakes on its first day (ISO), for a town whose
    residents plan as they wake: it opens then, with everyone else still in bed."""

    from ..cognition.planning import waking_at
    from ..config import repo_path
    from ..scenario.loader import load_scenario

    scenario = load_scenario(repo_path(cfg.scenario.path), population=cfg.scenario.population, candidacy_seed_policy=cfg.scenario.candidacy_seed_policy)
    day = datetime.fromisoformat(str(cfg.scenario.start)).date()
    times = [t for t in (waking_at(ident, day) for ident in scenario.identities().values()) if t is not None]
    return min(times).replace(second=0, microsecond=0).isoformat() if times else None


class TabTown:
    def __init__(
        self,
        run_dir: str | Path,
        *,
        mind: str | None = None,
        residents: int | None = None,
        depth: str = "mind",
        memory: str | None = None,
        config: str = CONFIG,
        overrides: list[str] | None = None,
        speed: str = "normal",
        paused: bool = False,
    ):
        self.run_dir = Path(run_dir)
        # one step per commit: a question from the model costs one repeated step, never thirty
        sets = [*(overrides or []), *(mind_overrides(mind, depth) if mind is not None else []), "output.checkpoint_every_steps=1"]
        if (self.run_dir / "state.sqlite").exists() and (self.run_dir / "config.yaml").exists():
            self.cfg: GAConfig = load_run_config(self.run_dir, sets)
            self.resumed = True
        else:
            modelled = bool(mind) and mind != SCRIPTED
            # a new town with a model for a mind remembers by meaning unless told otherwise
            sets = [*cast_overrides(residents), *memory_overrides(memory or ("meaning" if modelled else "words")), *sets]
            sets += [] if mind is not None else mind_overrides(SCRIPTED)
            self.cfg = load_config(config, overrides=sets)
            if not any(o.startswith("scenario.start=") for o in overrides or []):
                # the town opens as its first resident wakes; at seven where everyone plans at once
                opens = (first_waking(self.cfg) if self.cfg.planning.at_waking else None) or f"{self.cfg.scenario.start.date().isoformat()}T07:00:00"
                self.cfg = load_config(config, overrides=[*sets, f"scenario.start={json.dumps(opens)}"])
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.resumed = False
        save_config(self.cfg, self.run_dir)
        self.session = GameSession(self.cfg, self.run_dir, speed=speed, paused=paused)
        self.sim = self.session.sim
        inner = self.sim.rt.provider
        self.model: DeferredLLM | None = inner if isinstance(inner, DeferredLLM) else None
        vectors = self.sim.rt.embeddings.provider
        self.embedder: DeferredEmbedding | None = vectors if isinstance(vectors, DeferredEmbedding) else None
        if self.embedder is not None:
            self.sim.flush_hooks.append(self._hold_for_vectors)  # before anything is committed
        self._script = MockLLM(seed=self.cfg.run.seed)
        self._reader: Database | None = None
        self._data: Any = None
        self._info: dict[str, Any] | None = None
        self._map: dict[str, Any] | None = None
        self.repeats = 0  # steps run again because the model had to answer first
        self.embedded = 0  # texts turned into vectors by the page's embedding model
        self.embed_rounds = 0
        # what the last commit looked like outside the database: the ledger's occurrence counters
        # and the feed the page has been shown; a rollback returns to exactly this
        self._mark: tuple[dict[str, int], int] = ({}, 0)
        self._recounted = not self.resumed

    # ------------------------------------------------------------------ the town's loop
    def tick(self) -> dict[str, Any]:
        """One pass. ``{"wait": seconds}``, or ``{"need": request}`` when the model must answer."""

        session = self.session
        try:
            if session._ready and not (session.error or session.paused or session.finished):
                # what the player did is its own unit of work: a reply is shown as soon as its
                # own question is answered, not when everyone else's thinking for the step is done
                session._service_actions()
                self._commit()
            wait = session.iterate()
            if session._ready and not self._recounted:
                # a town reopened from storage: everything in its ledger has been used already
                self.sim.rt.ledger.reset_counts(10**9)
                self._recounted = True
            self._commit()
        except Deferred as need:
            self._roll_back()
            if self.embedder is not None and self.embedder.missing:
                # the pass ran on stand-in vectors: whatever it was about to ask the model is
                # void; the real vectors first
                return {"need": self.embedder.need()}
            thought: dict[str, Any] = {"task": need.payload.get("task"), "since": time.time()}
            heard = self._just_said(need.payload)
            if heard:
                thought["heard"] = heard
            with session.lock:
                session._thinking[need.payload.get("agent_id") or "town"] = thought
            return {"need": need.payload}
        except Exception as exc:  # shown to the visitor with a Retry button, as the engine thread would
            self._roll_back()
            if self.embedder is not None and self.embedder.missing:
                return {"need": self.embedder.need()}  # it stumbled on a stand-in; run it on the real vectors
            session._failed("error", f"{type(exc).__name__}: {exc}")
            return {"wait": 0.5, "status": "error"}
        return {"wait": wait, "status": session.status}

    def _just_said(self, need: dict[str, Any]) -> dict[str, str] | None:
        """A conversation is written line by line while the town's clock stands still. The line
        the other speaker has just been given (it is in the ledger, and in this question's
        transcript) is shown over their head while this one thinks of an answer."""

        if need.get("task") != "dialogue_turn":
            return None
        ledger = self.sim.rt.ledger
        with ledger._lock:
            row = ledger.conn.execute(
                "SELECT agent_id, parsed_json FROM calls WHERE scope=? AND task='dialogue_turn' AND status='ok' AND step=? ORDER BY id DESC LIMIT 1",
                (ledger.scope, self.sim.clock.step),
            ).fetchone()
        if row is None or row["agent_id"] == need.get("agent_id") or not row["parsed_json"]:
            return None
        text = str(json.loads(row["parsed_json"]).get("utterance") or "").strip()
        if not text or text not in str(need.get("prompt") or ""):
            return None  # a line from another conversation of the same step
        return {"from": row["agent_id"], "text": text}

    def _hold_for_vectors(self) -> None:
        """Nothing computed from stand-in vectors is ever saved (``DeferredEmbedding``)."""

        if self.embedder is not None and self.embedder.missing:
            raise Deferred("embed", {"kind": "embed"})

    def _commit(self) -> None:
        sim = self.sim
        sim.svc.states.flush()
        sim.spatial.flush()
        sim.world_state.flush()
        for hook in sim.flush_hooks:  # the game layer's own store among them
            hook()
        sim.db.commit()
        self._mark = (dict(sim.rt.ledger._counts), self.session._feed_seq)
        if self.embedder is not None:
            self.embedder.settle()

    def _roll_back(self) -> None:
        """Undo the unanswered work: back to the last commit, caches dropped, and nothing the
        page was shown since then stays in its feed (the work will be done again)."""

        sim, session = self.sim, self.session
        sim.db.rollback()
        sim._invalidate()
        if sim.initialized():
            sim.clock.step = int(sim.db.get_meta("next_step", 0))
        counts, feed_seq = self._mark
        with sim.rt.ledger._lock:
            sim.rt.ledger._counts = dict(counts)
        with session.lock:
            while session._feed and session._feed[-1]["seq"] > feed_seq:
                session._feed.pop()
            session._feed_seq = feed_seq
        self.repeats += 1

    def deliver(
        self, key: str, text: str, input_tokens: int | None = None, output_tokens: int | None = None, finish: str = "stop", latency_ms: float = 0.0
    ) -> None:
        self._require_model().deliver(key, text, input_tokens=input_tokens, output_tokens=output_tokens, finish=finish, latency_ms=latency_ms)
        self._done_thinking()

    def deliver_vectors(self, key: str, data: str, count: int) -> None:
        """The embedding model's answer to an ``embed`` need: ``count`` vectors as base64 of
        their little-endian float32 numbers, in the order the texts were asked."""

        embedder = self._require_embedder()
        if embedder.need()["key"] != key:
            return  # an answer to a question no longer open
        flat = np.frombuffer(base64.b64decode(data), dtype="<f4")
        if count <= 0 or flat.size % count:
            raise ValueError(f"{flat.size} numbers do not make {count} vectors")
        embedder.deliver(flat.reshape(count, -1))
        self.embedded += count
        self.embed_rounds += 1

    def fail(self, key: str, message: str, retryable: bool = False) -> None:
        if self.embedder is not None and self.embedder.missing and self.embedder.need()["key"] == key:
            self.session._failed("error", f"the memory model in this tab could not answer: {message}")
            return
        self._require_model().fail(key, message, retryable=retryable)
        self._done_thinking()

    def scripted_answer(self, key: str) -> str:
        """What the offline fixture would say to the pending question (for tests of the page's plumbing)."""

        request = self._require_model().pending[key]
        return self._script.complete(request).text

    def _require_model(self) -> DeferredLLM:
        if self.model is None:
            raise ValueError("this town's residents are scripted; there is no model to answer for")
        return self.model

    def _require_embedder(self) -> DeferredEmbedding:
        if self.embedder is None:
            raise ValueError("this town searches its memory by words; there is no embedding model to answer for")
        return self.embedder

    def scripted_vectors(self, key: str) -> list[Any]:
        """Stand-in vectors for the open ``embed`` need as ``[base64, count]`` (for tests of the page's plumbing)."""

        embedder = self._require_embedder()
        need = embedder.need()
        if need["key"] != key:
            raise KeyError("no such question")
        vecs = embedder._stand_in.embed(need["texts"]).astype("<f4")
        return [base64.b64encode(vecs.tobytes()).decode(), len(need["texts"])]

    def _done_thinking(self) -> None:
        with self.session.lock:
            self.session._thinking.clear()

    # ------------------------------------------------------------------ what the interface asks
    def info(self) -> dict[str, Any]:
        if self._info is None:
            self._info = {
                **town_info(self.session),
                "tab": True,
                "mind": self.cfg.providers.llm.model if self.model else SCRIPTED,
                "resumed": self.resumed,
                # how residents search their memory, and the model the page must run for it
                "memory": "meaning" if self.embedder else "words",
                "embed_model": self.embedder.model_id if self.embedder else None,
            }
        return self._info

    def map(self) -> dict[str, Any]:
        if self._map is None:
            self._map = town_map(self.session)
        return self._map

    def poll(self, since_step: int = -2, since_feed: int = 0) -> dict[str, Any]:
        return self.session.poll(int(since_step), int(since_feed))

    def action(self, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.session.submit(kind, payload or {})

    def validate_build(self, ops: list[dict[str, Any]]) -> dict[str, Any]:
        return self.session.validate_build(ops)

    def control(self, action: str, speed: str | None = None) -> dict[str, Any]:
        return self.session.control(action, speed)

    def _rows(self, sql: str, params: tuple = ()) -> list[Any]:
        if self._reader is None:
            self._reader = Database(self.run_dir / "state.sqlite", read_only=True)
        return self._reader.query(sql, params)

    def resident(self, aid: str) -> dict[str, Any]:
        return resident_detail(self.session, aid, self._rows)

    def object(self, address: str) -> dict[str, Any]:
        if not self.sim.world.exists(address):
            raise KeyError("unknown object")
        return object_info(self.session, address)

    def research(self, path: str) -> Any:
        if self._data is None:
            from ..viewer.data import RunData

            self._data = RunData(self.run_dir)
        return dispatch(self._data, path)

    def stats(self) -> dict[str, Any]:
        usage = self.sim.rt.budget.usage
        return {
            "step": self.sim.clock.step,
            "calls": usage.calls,
            "answered_from_memory": usage.cache_hits,
            "repeated_steps": self.repeats,
            "embedded": self.embedded,
            "embed_rounds": self.embed_rounds,
        }

    # ------------------------------------------------------------------ one door for the page
    def call(self, method: str, args_json: str = "[]") -> str:
        """Run ``method`` with JSON arguments; always returns JSON: ``{"ok": result}`` or
        ``{"error": {"status": code, "detail": text}}`` with the status an HTTP server would use."""

        if method.startswith("_") or method in ("call", "close") or not callable(getattr(self, method, None)):
            return json.dumps({"error": {"status": 404, "detail": f"no such method {method}"}})
        try:
            return json.dumps({"ok": getattr(self, method)(*json.loads(args_json))}, default=str)
        except PermissionError as exc:
            return json.dumps({"error": {"status": 409, "detail": str(exc)}})
        except (NotFound, KeyError) as exc:
            return json.dumps({"error": {"status": 404, "detail": str(exc).strip("'\"")}})
        except (ValueError, TypeError) as exc:
            return json.dumps({"error": {"status": 400, "detail": str(exc)}})

    def close(self) -> None:
        """Save and release the town (the page calls this before it opens the town with another mind)."""

        sim = self.sim
        if self.session._ready and not self.session.error:
            sim.finish(sim.wind_down())
        for db in (self._reader, getattr(self._data, "db", None)):
            if db is not None:
                db.close()
        sim.close()
