"""Client-side rate limiting for hosted model APIs, so a town stays inside a free tier.

Free API plans cap requests and tokens per minute and per day (docs/deploy.md §2d lists the
current ones). Rather than hit 429s and back off blindly, ``RateLimitedProvider`` wraps any
provider and waits *before* a call whenever the next request would exceed a configured limit.
Windows are sliding (60 s and 24 h), which is conservative against providers that reset at a
fixed clock time. Token counts are reserved from the prompt estimate plus the output ceiling,
then settled to the provider's reported usage once the reply is in.

The wrapper is transparent to the ledger and to replay: it changes *when* a call happens, never
what is sent or recorded. The simulated clock simply falls behind wall-clock time while waiting.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .base import LLMRequest, LLMResponse, estimate_tokens

MINUTE = 60.0
DAY = 86_400.0


@dataclass(frozen=True)
class RateLimits:
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    requests_per_day: int | None = None
    tokens_per_day: int | None = None
    # Fraction of each limit the limiter actually uses, leaving headroom for the provider's own
    # counting (it counts real tokens; we estimate before the call).
    headroom: float = 0.9

    def any(self) -> bool:
        return any(v is not None for v in (self.requests_per_minute, self.tokens_per_minute, self.requests_per_day, self.tokens_per_day))

    def describe(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class _Window:
    """Events (timestamp, count) within a sliding window; sums requests and tokens."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self.events: deque[tuple[float, int]] = deque()
        self.tokens = 0

    def prune(self, now: float) -> None:
        while self.events and now - self.events[0][0] >= self.seconds:
            _, n = self.events.popleft()
            self.tokens -= n

    def add(self, now: float, tokens: int) -> None:
        self.events.append((now, tokens))
        self.tokens += tokens

    def settle(self, delta: int) -> None:
        """Adjust the most recent reservation to the real token count."""

        if not self.events:
            return
        t, n = self.events[-1]
        self.events[-1] = (t, max(0, n + delta))
        self.tokens += max(-n, delta)

    def wait_for(self, now: float, requests_cap: int | None, tokens_cap: int | None, tokens: int) -> float:
        """Seconds until an event of ``tokens`` fits, 0 if it fits now."""

        self.prune(now)
        wait = 0.0
        if requests_cap is not None and len(self.events) >= requests_cap:
            wait = max(wait, self.events[len(self.events) - requests_cap][0] + self.seconds - now)
        if tokens_cap is not None and self.tokens + tokens > tokens_cap:
            # release events oldest-first until the new one fits
            running = self.tokens
            for t, n in self.events:
                running -= n
                if running + tokens <= tokens_cap:
                    wait = max(wait, t + self.seconds - now)
                    break
            else:
                wait = max(wait, (self.events[-1][0] + self.seconds - now) if self.events else 0.0)
        return max(0.0, wait)


class RateLimiter:
    def __init__(self, limits: RateLimits, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.limits = limits
        self.clock = clock
        self.sleep = sleep
        self.minute = _Window(MINUTE)
        self.day = _Window(DAY)
        self.waited_s = 0.0
        self.waits = 0
        self._lock = threading.Lock()  # callers may be several model-call threads

    def _cap(self, value: int | None) -> int | None:
        return None if value is None else max(1, int(value * self.limits.headroom))

    def acquire(self, tokens: int) -> float:
        """Block until a call of ``tokens`` fits in every window, then reserve it. Returns seconds waited."""

        total = 0.0
        while True:
            with self._lock:
                now = self.clock()
                wait = max(
                    self.minute.wait_for(now, self._cap(self.limits.requests_per_minute), self._cap(self.limits.tokens_per_minute), tokens),
                    self.day.wait_for(now, self._cap(self.limits.requests_per_day), self._cap(self.limits.tokens_per_day), tokens),
                )
                if wait <= 0:
                    self.minute.add(now, tokens)
                    self.day.add(now, tokens)
                    if total:
                        self.waits += 1
                        self.waited_s += total
                    return total
            self.sleep(wait)
            total += wait

    def settle(self, reserved: int, actual: int) -> None:
        """Replace a reservation with the real token count (approximate when calls overlap)."""

        delta = actual - reserved
        with self._lock:
            self.minute.settle(delta)
            self.day.settle(delta)

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        self.minute.prune(now)
        self.day.prune(now)
        return {
            "minute": {"requests": len(self.minute.events), "tokens": self.minute.tokens},
            "day": {"requests": len(self.day.events), "tokens": self.day.tokens},
            "waits": self.waits,
            "waited_s": round(self.waited_s, 1),
        }


class RateLimitedProvider:
    """A provider that never sends more than its plan allows."""

    def __init__(self, inner: Any, limits: RateLimits, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.inner = inner
        self.limiter = RateLimiter(limits, clock=clock, sleep=sleep)
        self.name = getattr(inner, "name", "provider")

    def describe(self) -> dict[str, Any]:
        d = dict(self.inner.describe()) if hasattr(self.inner, "describe") else {"provider": self.name}
        d["rate_limit"] = self.limiter.limits.describe()
        return d

    def complete(self, request: LLMRequest) -> LLMResponse:
        reserved = estimate_tokens(request.system + request.prompt) + request.max_output_tokens
        self.limiter.acquire(reserved)
        response = self.inner.complete(request)
        self.limiter.settle(reserved, response.input_tokens + response.output_tokens)
        return response

    def __getattr__(self, item: str) -> Any:  # pass-through for provider-specific attributes (model, client, ...)
        return getattr(self.inner, item)
