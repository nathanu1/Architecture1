"""Parallel deciding: residents think at the same time, in an order that never depends on timing.

A step used to finish one resident's whole turn (perceive, plan, choose a place, react) before
the next resident began, so a town waited on one model call at a time. On a server that can
answer several requests at once (Ollama with ``OLLAMA_NUM_PARALLEL``, llama.cpp ``--parallel``,
vLLM) that leaves most of the machine idle.

``RoundScheduler`` runs the residents' turns in **rounds**:

1. *Think.* Each resident with work left runs, one at a time and in the town's fixed order,
   until its turn either ends or reaches a model task (``LLMGateway.run``). Only one resident
   touches the world at any moment, so there are no data races and no locks in engine code.
2. *Ask.* All model tasks reached in the round are sent together, up to ``workers`` at once.
   This is the only concurrent part, and it touches nothing but the provider, the call ledger
   and the budget (which carry their own locks).
3. Residents resume with their answers in the same fixed order, and the next round begins.

Which resident runs when depends only on *how many* model tasks each one makes, never on how
long a reply took. A model task is a pause point whether it is answered by the model, by a
habit or by the ledger, so a replay (where every answer is instant) interleaves exactly as the
recorded run did. With a provider that is a function of its request, any ``workers`` value
gives the same town.

The interleaving differs from the sequential engine: a resident paused on a model task can be
overtaken, within the step, by residents later in the order. That is why the setting is its own
fidelity row (``engine.parallel_calls``, class X when above 1) and off by default.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class _Cancelled(BaseException):
    """Unwinds a paused turn when the step is abandoned (another resident's turn failed)."""


class _Turn:
    __slots__ = ("back", "cancel", "error", "fn", "go", "job", "key", "outcome", "prepare", "state")

    def __init__(self, key: str, fn: Callable[[], None]):
        self.key = key
        self.fn = fn
        # Two locks used as hand-off signals (held = "not yet"): the engine releases ``go`` to
        # let the turn run, the turn releases ``back`` when it pauses or ends.
        self.go = threading.Lock()
        self.back = threading.Lock()
        self.go.acquire()
        self.back.acquire()
        self.state = "new"  # new | paused | done
        self.job: Callable[[], Any] | None = None
        self.prepare: Callable[[], None] | None = None
        self.outcome: tuple[bool, Any] | None = None  # (ok, value or exception)
        self.error: BaseException | None = None
        self.cancel = False


class RoundScheduler:
    def __init__(self, workers: int, *, concurrent: bool = True):
        self.workers = max(1, int(workers))
        # A provider that is not safe to call from several threads is asked in order instead;
        # the rounds (and so the town) are the same either way.
        self.concurrent = concurrent and self.workers > 1
        self._local = threading.local()
        self._turns: ThreadPoolExecutor | None = None
        self._turn_threads = 0
        self._io: ThreadPoolExecutor | None = None
        # rounds/tasks count every pause; model_* count only tasks that reached the model:
        # model_calls is what a sequential engine waits for one by one, model_waits is what the
        # rounds wait for (the longest task of each round), so their ratio is the gain a server
        # with enough parallel capacity can deliver.
        self.stats = {"steps": 0, "rounds": 0, "tasks": 0, "widest": 0, "model_calls": 0, "model_waits": 0}

    # ------------------------------------------------------------------ called by the gateway
    def in_turn(self) -> bool:
        return getattr(self._local, "turn", None) is not None

    def defer(self, job: Callable[[], Any], prepare: Callable[[], None] | None = None) -> Any:
        """Pause the calling turn until the round's model tasks are answered; return this one's.

        ``prepare`` runs on the engine thread just before the round is asked, in the town's
        fixed order (the gateway reserves the task's call ids there).
        """

        turn: _Turn = self._local.turn
        turn.job = job
        turn.prepare = prepare
        turn.state = "paused"
        turn.back.release()
        turn.go.acquire()
        if turn.cancel:
            raise _Cancelled()
        ok, value = turn.outcome  # type: ignore[misc]
        turn.outcome = None
        if not ok:
            raise value
        return value

    # ------------------------------------------------------------------ called by the engine
    def run(self, turns: list[tuple[str, Callable[[], None]]]) -> None:
        """Run every turn to completion. Raises the first failure in the town's order."""

        if not turns:
            return
        if self._turns is None or self._turn_threads < len(turns):
            if self._turns is not None:
                self._turns.shutdown(wait=True)
            self._turn_threads = len(turns)
            self._turns = ThreadPoolExecutor(max_workers=len(turns), thread_name_prefix="resident")
        all_turns = [_Turn(key, fn) for key, fn in turns]
        for t in all_turns:
            self._turns.submit(self._body, t)
        self.stats["steps"] += 1
        active = all_turns
        try:
            while active:
                for t in active:  # think: strictly one at a time, in order
                    t.go.release()
                    t.back.acquire()
                failed = next((t for t in active if t.state == "done" and t.error is not None), None)
                if failed is not None:
                    raise failed.error  # type: ignore[misc]
                active = [t for t in active if t.state == "paused"]
                if active:
                    self._ask(active)
        finally:
            for t in all_turns:  # abandon whatever is still paused, running or never started
                while t.state != "done":
                    t.cancel = True
                    try:
                        t.go.release()
                    except RuntimeError:  # interrupted while this turn was running: it is already free to go
                        pass
                    t.back.acquire()

    def close(self) -> None:
        for pool in (self._turns, self._io):
            if pool is not None:
                pool.shutdown(wait=False)
        self._turns = self._io = None

    # ------------------------------------------------------------------ internals
    def _body(self, turn: _Turn) -> None:
        turn.go.acquire()
        self._local.turn = turn
        try:
            if turn.cancel:
                raise _Cancelled()
            turn.fn()
        except _Cancelled:
            pass
        except BaseException as exc:  # noqa: BLE001 - re-raised by run() on the engine thread
            turn.error = exc
        finally:
            self._local.turn = None
            turn.state = "done"
            turn.back.release()

    def _ask(self, paused: list[_Turn]) -> None:
        self.stats["rounds"] += 1
        self.stats["tasks"] += len(paused)
        self.stats["widest"] = max(self.stats["widest"], len(paused))
        for t in paused:
            if t.prepare is not None:
                t.prepare()
        if not self.concurrent or len(paused) == 1:
            for t in paused:
                t.outcome = _outcome(t.job)
        else:
            if self._io is None:
                self._io = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="model-call")
            futures = [self._io.submit(_outcome, t.job) for t in paused]
            for t, f in zip(paused, futures, strict=True):
                t.outcome = f.result()
        depths = [len(getattr(v, "call_ids", ())) for ok, v in (t.outcome for t in paused) if ok and getattr(v, "cached", True) is False]
        if depths:
            self.stats["model_calls"] += sum(depths)
            self.stats["model_waits"] += max(depths)


def _outcome(job: Callable[[], Any] | None) -> tuple[bool, Any]:
    try:
        return True, job()  # type: ignore[misc]
    except Exception as exc:  # noqa: BLE001 - delivered to the resident's turn, which re-raises it
        return False, exc
