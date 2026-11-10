"""The single path every model call takes (spec O-1).

``LLMGateway.run(task, variables)`` renders the versioned template, consults the
exact-request ledger, enforces the budget, calls the provider with bounded retries, validates
the JSON output against the task schema (plus an optional semantic check), performs bounded
repair attempts, and records everything. It never invents an output: if repairs fail it
raises ``TaskFailed``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ..db import sha256_text, stable_json
from ..prompting import PromptRegistry, PromptTemplate
from .base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ProviderRefusal,
    ProviderTruncated,
    ReplayMiss,
    TaskFailed,
    estimate_tokens,
)
from .ledger import CallLedger
from .pricing import PriceTable
from .schema import decoding_schema, strict_json_schema

T = TypeVar("T", bound=BaseModel)

Validator = Callable[[Any], list[str]]


@dataclass
class TaskResult(Generic[T]):
    output: T
    call_ids: list[int]
    cached: bool
    raw: str
    template_id: str


def extract_json(text: str) -> Any:
    """Parse the first JSON object in ``text`` (tolerates code fences and leading prose)."""

    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in output")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj


@dataclass
class GatewaySettings:
    model: str
    max_output_tokens: int | None = None
    effort: str | None = None
    temperature: float | None = None
    max_retries: int = 2
    max_validation_repairs: int = 1
    backoff_s: float = 2.0
    task_overrides: dict[str, dict[str, Any]] | None = None
    zero_cost: bool = False  # a model on your own machine: every call costs 0 USD
    # Tasks whose identical prompts are answered from the ledger's first valid reply instead of a
    # new call (research extension for long-running towns; off by default). It trades sampling
    # variety on repeated mechanical prompts for about a third fewer calls.
    memoize_tasks: frozenset[str] = frozenset()
    # Tasks answered from the ledger when their *structured inputs* recur (the ``_``-prefixed
    # variables: the activity and offered places, the memory text and kind, ...), even though
    # the rendered prompt differs because the date or the dynamic summary changed. Like a
    # habit: the same situation gets the same answer without deliberation. Off by default.
    habit_tasks: frozenset[str] = frozenset()
    # Default model of each named provider pool (config providers.llm.pools); a task override
    # with ``provider: <name>`` and no ``model`` uses it.
    pool_models: dict[str, str] | None = None


class LLMGateway:
    def __init__(
        self,
        provider: LLMProvider,
        registry: PromptRegistry,
        ledger: CallLedger,
        budget: Any,
        settings: GatewaySettings,
        *,
        pricing: PriceTable | None = None,
        step_getter: Callable[[], int | None] | None = None,
        replay: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        pools: dict[str, LLMProvider] | None = None,
    ):
        self.provider = provider
        self.pools: dict[str, LLMProvider] = dict(pools or {})
        for name in {o.get("provider") for o in (settings.task_overrides or {}).values()} - {None}:
            if name not in self.pools and not replay:  # a replay never calls a provider
                raise ValueError(f"task override routes to unknown provider pool {name!r}")
        self.registry = registry
        self.ledger = ledger
        self.budget = budget
        self.settings = settings
        self.pricing = pricing or PriceTable(None)
        self.step_getter = step_getter or (lambda: None)
        self.replay = replay
        self.sleep = sleep
        # Parallel deciding (simulation/parallel.py): when set and the caller is a resident's
        # turn, a task pauses the turn and is answered with the rest of its round.
        self.scheduler: Any = None
        self._tls = threading.local()  # the call ids reserved for the task this thread is answering

    # ------------------------------------------------------------------ public
    def run(
        self,
        task: str,
        variables: dict[str, Any],
        *,
        agent_id: str | None = None,
        sim_time: datetime | None = None,
        purpose: str | None = None,
        validate: Validator | None = None,
        constraints: dict[str, dict[str, Any]] | None = None,
    ) -> TaskResult[Any]:
        """Run one task. ``constraints`` restate parts of ``validate`` as JSON-schema keywords
        (see ``providers.schema.decoding_schema``) for providers that decode within a grammar."""

        scheduler = self.scheduler
        if scheduler is not None and scheduler.in_turn():
            block = (1 + self.settings.max_validation_repairs) * (1 + self.settings.max_retries)
            ids: list[Any] = []

            def reserve() -> None:  # runs before the round is asked, in the town's fixed order
                if self.ledger.readonly_scope is None:
                    base = self.ledger.reserve_ids(block)
                    ids.append(iter(range(base, base + block)))

            def job() -> TaskResult[Any]:
                self._tls.ids = ids[0] if ids else None
                try:
                    return self._run(task, variables, agent_id=agent_id, sim_time=sim_time, purpose=purpose, validate=validate, constraints=constraints)
                finally:
                    self._tls.ids = None

            return scheduler.defer(job, prepare=reserve)
        return self._run(task, variables, agent_id=agent_id, sim_time=sim_time, purpose=purpose, validate=validate, constraints=constraints)

    def _run(
        self,
        task: str,
        variables: dict[str, Any],
        *,
        agent_id: str | None = None,
        sim_time: datetime | None = None,
        purpose: str | None = None,
        validate: Validator | None = None,
        constraints: dict[str, dict[str, Any]] | None = None,
    ) -> TaskResult[Any]:
        template = self.registry.get(task)
        system, prompt = template.render(variables)
        schema = strict_json_schema(template.output_model)
        decoding = decoding_schema(schema, constraints) if constraints else None
        knobs = self._knobs(template)
        habit_key = self.habit_key(task, template, knobs, agent_id, variables) if task in self.settings.habit_tasks else None
        if habit_key is not None:
            habit = self.ledger.lookup_habit(habit_key)
            if habit is not None:
                parsed, errors = self._validate(habit.raw_output or "", template.output_model, validate)
                if not errors:
                    self.budget.record_cache_hit()
                    return TaskResult(parsed, [habit.id], True, habit.raw_output or "", template.template_id)
        call_ids: list[int] = []
        all_errors: list[str] = []
        attempt_prompt = prompt
        any_cached = True
        for attempt in range(1 + self.settings.max_validation_repairs):
            request = LLMRequest(
                task=task,
                template_id=template.template_id,
                template_hash=template.sha256,
                system=system,
                prompt=attempt_prompt,
                output_schema=schema,
                model=knobs["model"],
                max_output_tokens=knobs["max_output_tokens"],
                effort=knobs["effort"],
                temperature=knobs["temperature"],
                agent_id=agent_id,
                purpose=purpose or task,
                sim_time=sim_time,
                variables=variables,
                attempt_kind="initial" if attempt == 0 else "repair",
                decoding_schema=decoding,
                pool=knobs["provider"],
            )
            raw, call_id, cached = self._call(request)
            call_ids.append(call_id)
            any_cached = any_cached and cached
            parsed, errors = self._validate(raw, template.output_model, validate)
            self._mark(call_id, parsed, errors)
            if not errors:
                if habit_key is not None:
                    self.ledger.remember_habit(habit_key, call_id)
                return TaskResult(parsed, call_ids, any_cached, raw, template.template_id)
            all_errors.extend(errors)
            attempt_prompt = (
                prompt
                + "\n\nYour previous answer was not usable:\n"
                + "\n".join(f"- {e}" for e in errors)
                + f"\nPrevious answer: {raw.strip()[:2000]}\nReturn corrected JSON only."
            )
        raise TaskFailed(task, "output invalid after bounded repairs", call_ids=call_ids, errors=all_errors)

    # ------------------------------------------------------------------ internals
    def _knobs(self, template: PromptTemplate) -> dict[str, Any]:
        knobs = {
            "max_output_tokens": template.max_output_tokens,
            "effort": template.effort,
            "temperature": self.settings.temperature,
            "model": self.settings.model,
            "provider": None,
        }
        if self.settings.max_output_tokens is not None:
            knobs["max_output_tokens"] = max(knobs["max_output_tokens"], self.settings.max_output_tokens)
        if self.settings.effort is not None:
            knobs["effort"] = self.settings.effort
        override = (self.settings.task_overrides or {}).get(template.id, {})
        if override.get("provider") is not None:
            knobs["provider"] = override["provider"]
            knobs["model"] = (self.settings.pool_models or {}).get(override["provider"], knobs["model"])
        for key in ("max_output_tokens", "effort", "temperature", "model"):
            if key in override:
                knobs[key] = override[key]
        return knobs

    def provider_for(self, request: LLMRequest) -> LLMProvider:
        return self.pools[request.pool] if request.pool else self.provider

    @staticmethod
    def habit_key(task: str, template: PromptTemplate, knobs: dict[str, Any], agent_id: str | None, variables: dict[str, Any]) -> str | None:
        """The situation a habit answers: task, template, model, agent and the structured inputs.

        Returns None when the task passes no structured (``_``-prefixed) inputs, because then the
        prompt text is the only description of the situation and a habit would be unsafe.
        """

        structured = {k: v for k, v in variables.items() if k.startswith("_")}
        if not structured:
            return None
        return sha256_text(
            stable_json(
                {
                    "task": task,
                    "template": template.template_id,
                    "template_hash": template.sha256,
                    "model": knobs["model"],
                    "agent_id": agent_id,
                    "inputs": structured,
                }
            )
        )

    def request_hash(self, request: LLMRequest) -> str:
        return sha256_text(
            stable_json(
                {
                    # The provider is not part of the key: the scope (run ID) already isolates
                    # runs, and replay must match the source run's requests (spec K-4).
                    "model": request.model,
                    "max_output_tokens": request.max_output_tokens,
                    "effort": request.effort,
                    "temperature": request.temperature,
                    "template": request.template_id,
                    "template_hash": request.template_hash,
                    "system": request.system,
                    "prompt": request.prompt,
                    "schema": request.output_schema,
                    "agent_id": request.agent_id,
                }
            )
        )

    def _call(self, request: LLMRequest) -> tuple[str, int, bool]:
        h = self.request_hash(request)
        if request.task in self.settings.memoize_tasks and request.attempt_kind == "initial":
            memo = self.ledger.lookup_memo(h)
            if memo is not None:
                self.budget.record_cache_hit()
                return memo.raw_output or "", memo.id, True
        last_error: ProviderError | None = None
        reserved = getattr(self._tls, "ids", None)  # set while answering a task of a parallel round
        for attempt in range(1 + self.settings.max_retries):
            # every attempt takes the next reserved id, used or not, so a re-executed step
            # numbers its remaining calls as the first execution would have
            call_id_hint = next(reserved) if reserved is not None else None
            occurrence = self.ledger.next_occurrence(h)
            record = self.ledger.lookup(h, occurrence)
            if record is not None:
                if reserved is None:
                    self.ledger.note_seen(record.id)
                self.budget.record_cache_hit()
                if record.status in ("refusal", "truncated"):
                    raise TaskFailed(request.task, record.error or record.status, call_ids=[record.id], errors=[record.status])
                if record.status == "error":
                    last_error = ProviderError(record.error or "error", retryable=record.error_retryable)
                    if last_error.retryable and attempt < self.settings.max_retries:
                        continue
                    raise last_error
                return record.raw_output or "", record.id, True
            if self.replay:
                raise ReplayMiss(f"no recorded response for {request.task} (agent={request.agent_id}, occurrence={occurrence})")
            est_in = estimate_tokens(request.system + request.prompt)
            self.budget.check(est_in, request.max_output_tokens)
            started = time.monotonic()
            try:
                response = self.provider_for(request).complete(request)
            except ProviderError as exc:
                latency = (time.monotonic() - started) * 1000
                call_id = self._record(request, h, occurrence, None, exc, latency, call_id_hint)
                last_error = exc
                if exc.retryable and attempt < self.settings.max_retries:
                    self.sleep(self.settings.backoff_s * (2**attempt))
                    continue
                if isinstance(exc, ProviderRefusal | ProviderTruncated):
                    raise TaskFailed(request.task, str(exc), call_ids=[call_id], errors=[exc.kind]) from exc
                raise
            latency = (time.monotonic() - started) * 1000
            call_id = self._record(request, h, occurrence, response, None, latency, call_id_hint)
            return response.text, call_id, False
        assert last_error is not None
        raise last_error

    def _record(
        self,
        request: LLMRequest,
        request_hash: str,
        occurrence: int,
        response: LLMResponse | None,
        error: ProviderError | None,
        latency_ms: float,
        call_id: int | None = None,
    ) -> int:
        settings = {
            "max_output_tokens": request.max_output_tokens,
            "effort": request.effort,
            "temperature": request.temperature,
        }
        if response is not None:
            cost = (
                0.0
                if self.settings.zero_cost
                else self.pricing.cost(
                    response.served_model or request.model,
                    response.input_tokens,
                    response.output_tokens,
                    response.cache_read_tokens,
                    response.cache_write_tokens,
                )
            )
            self.budget.record(response.input_tokens, response.output_tokens, cost)
            status = "received"
            fields = dict(
                served_model=response.served_model,
                raw_output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                tokens_estimated=1 if response.tokens_estimated else 0,
                cache_read_tokens=response.cache_read_tokens,
                cache_write_tokens=response.cache_write_tokens,
                cost_usd=cost,
                metadata_json=stable_json(response.metadata),
            )
        else:
            status = error.kind if error and error.kind in ("refusal", "truncated") else "error"
            fields = dict(
                error=str(error),
                error_retryable=1 if error and error.retryable else 0,
                metadata_json=stable_json(error.metadata if error else {}),
            )
            self.budget.record(0, 0, 0.0)
        explicit = {"id": call_id} if call_id is not None else {}
        recorded = self.ledger.record(
            **explicit,
            request_hash=request_hash,
            occurrence=occurrence,
            step=self.step_getter(),
            sim_time=request.sim_time.isoformat() if request.sim_time else None,
            task=request.task,
            template_id=request.template_id,
            template_hash=request.template_hash,
            agent_id=request.agent_id,
            purpose=request.purpose,
            provider=(f"{request.pool}:" if request.pool else "") + self.provider_for(request).name,
            model=request.model,
            settings_json=stable_json(settings),
            system=request.system,
            prompt=request.prompt,
            schema_json=stable_json(request.output_schema),
            status=status,
            latency_ms=latency_ms,
            attempt_kind=request.attempt_kind,
            **fields,
        )
        if call_id is None:
            self.ledger.note_seen(recorded)
        return recorded

    @staticmethod
    def _validate(raw: str, model: type[BaseModel], validate: Validator | None) -> tuple[Any, list[str]]:
        try:
            data = extract_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return None, [f"output is not valid JSON: {exc}"]
        try:
            parsed = model.model_validate(data)
        except ValidationError as exc:
            return None, [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        if validate is not None:
            errors = validate(parsed)
            if errors:
                return parsed, list(errors)
        return parsed, []

    def _mark(self, call_id: int, parsed: Any, errors: list[str]) -> None:
        if self.ledger.readonly_scope is not None:
            return
        with self.ledger._lock:
            self.ledger.conn.execute(
                "UPDATE calls SET status=?, parsed_json=?, validation_errors=? WHERE id=? AND status IN ('received','ok','invalid')",
                (
                    "invalid" if errors else "ok",
                    parsed.model_dump_json() if parsed is not None else None,
                    json.dumps(errors) if errors else None,
                    call_id,
                ),
            )
            self.ledger.conn.commit()
