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

import numpy as np

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


class DeferredEmbedding:
    """Vectors from an embedding model the town cannot call itself (the page's, on WebGPU).

    Meaning-based memory asks for many vectors in one step, so they are not fetched one by one.
    A text whose vector is not known yet gets a *stand-in* (a lexical hash vector of the same
    size) and is noted in ``missing``; the pass carries on and gathers every other text it
    needs. The driver then undoes the pass, has all of them embedded in one batch, ``deliver``s
    them and runs the pass again with the real vectors. Nothing computed from a stand-in
    survives: the driver refuses to commit while ``missing`` is not empty.
    """

    name = "browser"
    is_fixture = False
    revision: str | None = None
    MAX_CHARS = 1200  # well inside the 512-token window of the small embedding models

    def __init__(self, model: str, dims: int):
        from .embeddings import MockHashEmbedding

        self.model_id = model
        self.dims = int(dims)
        self.known: dict[str, np.ndarray] = {}
        self.missing: dict[str, None] = {}  # insertion-ordered set
        self._stand_in = MockHashEmbedding(self.dims)

    def describe(self) -> dict[str, Any]:
        return {"kind": "browser", "model": self.model_id, "dims": self.dims, "revision": None, "fixture": False, "local": True}

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            vec = self.known.get(text)
            if vec is None:
                self.missing[text] = None
                vec = self._stand_in.embed([text])[0]
            rows.append(vec)
        return np.stack(rows).astype(np.float32)

    def need(self) -> dict[str, Any]:
        """What to ask the page for: every text of the undone pass, shortened to the model's window."""

        texts = list(self.missing)
        key = hashlib.sha256("\x00".join(texts).encode()).hexdigest()
        return {"kind": "embed", "key": key, "task": "embed", "agent_id": None, "model": self.model_id, "texts": [t[: self.MAX_CHARS] for t in texts]}

    def deliver(self, vectors: Any) -> None:
        """The vectors for ``need()['texts']``, in order."""

        texts = list(self.missing)
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape != (len(texts), self.dims):
            raise ValueError(f"expected {len(texts)} vectors of {self.dims} numbers, got an array of shape {arr.shape}")
        if not np.isfinite(arr).all():
            raise ValueError("the embedding model returned numbers that are not finite")
        arr = arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-12)
        for text, vec in zip(texts, arr, strict=True):
            self.known[text] = vec
        self.missing.clear()

    def settle(self) -> None:
        """After a commit: the vectors used are in the run's own store now."""

        if len(self.known) > 4096:
            self.known.clear()
