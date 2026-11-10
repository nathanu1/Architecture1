"""A model the town cannot call itself: the answer comes from outside, later.

In a browser tab the language model lives in JavaScript (WebGPU) and answers asynchronously,
while the engine is ordinary synchronous Python with no threads. ``DeferredLLM`` bridges the two
without changing the engine:

1. the engine asks for a completion; nothing is known yet, so the provider raises ``Deferred``
   carrying the request;
2. the driver (``game/tab.py``) rolls the step back to its last commit and hands the request to
   whoever can answer it;
3. the answer is ``deliver``-ed, the step runs again, and this time the provider has the answer.
   The gateway records it in the ledger as any other call, so every later re-execution of the
   step finds it there and goes on to the next question.

A step with k model calls is therefore executed k+1 times. Steps cost milliseconds and model
calls cost seconds, and the engine's steps are transactional by design (that is what resume and
replay rest on), so the result is exactly the run a blocking provider would have produced.

``Deferred`` derives from ``BaseException`` so that no ``except Exception`` between the provider
and the driver can mistake it for a failure.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .base import LLMRequest, LLMResponse, ProviderError, ProviderTruncated
from .schema import inline_refs


class Deferred(BaseException):
    """The step cannot continue until ``payload`` (a model request) is answered."""

    def __init__(self, key: str, payload: dict[str, Any]):
        super().__init__(f"waiting for the model: {payload.get('task')}")
        self.key = key
        self.payload = payload


class DeferredLLM:
    name = "browser"
    concurrent_safe = False

    def __init__(self, model: str, *, runtime: str = "webgpu"):
        self.model = model
        self.runtime = runtime
        self.ready: dict[str, LLMResponse | ProviderError] = {}
        self.pending: dict[str, LLMRequest] = {}

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "runtime": self.runtime, "local": True}

    @staticmethod
    def key_of(request: LLMRequest) -> str:
        blob = "\x00".join([request.model, request.system, request.prompt, str(request.max_output_tokens), str(request.temperature)])
        return hashlib.sha256(blob.encode()).hexdigest()

    def complete(self, request: LLMRequest) -> LLMResponse:
        key = self.key_of(request)
        answer = self.ready.pop(key, None)
        if answer is not None:
            self.pending.pop(key, None)
            if isinstance(answer, ProviderError):
                raise answer
            return answer
        self.pending = {key: request}  # one question at a time; an abandoned one is forgotten
        raise Deferred(
            key,
            {
                "key": key,
                "task": request.task,
                "agent_id": request.agent_id,
                "model": request.model,
                "system": request.system,
                "prompt": request.prompt,
                "schema": request.decoding_schema or inline_refs(request.output_schema),
                "max_tokens": request.max_output_tokens,
                "temperature": request.temperature,
            },
        )

    def deliver(
        self, key: str, text: str, *, input_tokens: int | None = None, output_tokens: int | None = None, finish: str = "stop", latency_ms: float = 0.0
    ) -> None:
        """The answer to the request raised as ``Deferred(key)``; consumed when the step runs again."""

        from .base import estimate_tokens

        request = self.pending.get(key)
        if finish == "length":
            self.ready = {key: ProviderTruncated("the answer hit its length limit before the JSON was complete", metadata={"finish_reason": finish})}
            return
        estimated = input_tokens is None or output_tokens is None
        self.ready = {
            key: LLMResponse(
                text=text,
                input_tokens=int(input_tokens if input_tokens is not None else estimate_tokens((request.system + request.prompt) if request else text)),
                output_tokens=int(output_tokens if output_tokens is not None else estimate_tokens(text)),
                served_model=request.model if request else self.model,
                stop_reason=finish,
                tokens_estimated=estimated,
                latency_ms=latency_ms,
                metadata={"finish_reason": finish, "runtime": self.runtime},
            )
        }

    def fail(self, key: str, message: str, *, retryable: bool = False) -> None:
        self.ready = {key: ProviderError(f"the model in this tab could not answer: {message}", retryable=retryable)}
