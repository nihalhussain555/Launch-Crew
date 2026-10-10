"""Thin LLM wrapper. Agents only talk to `LLMClient`; the provider (Groq, mock, ...) is swappable.

Responsibilities:
  * concurrency limit (asyncio.Semaphore, LLM_MAX_CONCURRENCY)
  * 429 / transient-error retries: honour `retry-after`, else exponential backoff with jitter
  * Groq key pooling (GROQ_API_KEYS): a 429 cools down that one key and the call moves to the next
  * surfacing "rate limited, retrying" via an `on_retry` callback (-> SSE event)
  * token usage returned on every result (the run-level budget is enforced by RunContext)
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from app.config import Settings


# ----------------------------------------------------------------- data types
@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_message: dict | None = None  # assistant message to append when continuing a tool loop
    finish_reason: str = "stop"


# ----------------------------------------------------------------- errors
class LLMError(Exception):
    """Non-retryable LLM failure."""


class LLMOutputError(LLMError):
    """The model produced unusable output (e.g. Groq json_validate_failed)."""


class LLMToolRequestError(LLMOutputError):
    """The model tried to call a tool the request never registered.

    Groq refuses it with HTTP 400 ("Tool choice is none, but model called a tool") because a
    tool-less request has nothing to execute the call. Retrying the same request cannot help; the
    caller has to drop the tool instructions from it.
    """


def classify_bad_request(message: str) -> type[LLMError]:
    """Split Groq's HTTP 400s into the recovery each one needs.

    400 is not one failure: `json_validate_failed` means the model answered in the wrong shape and
    a corrective retry can work, while a tool-call refusal means the prompt invited a tool that the
    request does not carry.
    """
    low = message.lower()
    if "tool_use_failed" in low or "called a tool" in low or "tool choice is none" in low:
        return LLMToolRequestError
    if "json_validate_failed" in low or "invalid_json" in low:
        return LLMOutputError
    return LLMError


class RateLimitedError(LLMError):
    def __init__(self, retry_after: float | None = None, message: str = "rate limited (429)"):
        super().__init__(message)
        self.retry_after = retry_after


class TransientLLMError(LLMError):
    def __init__(self, message: str = "transient LLM error", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMProvider(Protocol):
    async def complete(
        self, *, agent: str, model: str, messages: list[dict], json_mode: bool,
        tools: list[dict] | None, temperature: float, max_tokens: int,
    ) -> LLMResult: ...


# ----------------------------------------------------------------- retry / backoff
MAX_HONOURED_RETRY_AFTER = 120.0


def compute_backoff(
    attempt: int, retry_after: float | None, base: float = 1.0, cap: float = 30.0,
    rng: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait before retry number `attempt` (0-based).

    * If the server sent retry-after, honour it (bounded) plus a little jitter.
    * Otherwise exponential backoff with "equal jitter": delay in [exp/2, exp], exp = min(cap, base*2^attempt).
    """
    if retry_after is not None:
        return min(max(retry_after, 0.0), MAX_HONOURED_RETRY_AFTER) + rng() * 0.5
    exp = min(cap, base * (2 ** attempt))
    return exp / 2 + rng() * exp / 2


async def call_with_retries(
    fn: Callable[[], Awaitable[Any]],
    *,
    max_retries: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    on_retry: Callable[[dict], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: Callable[[], float] = random.random,
):
    attempt = 0
    while True:
        try:
            return await fn()
        except (RateLimitedError, TransientLLMError) as exc:
            if attempt >= max_retries:
                raise
            delay = compute_backoff(attempt, exc.retry_after, base_delay, max_delay, rng)
            if on_retry:
                await on_retry({
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "retry_in": round(delay, 2),
                    "reason": "rate_limited" if isinstance(exc, RateLimitedError) else "transient_error",
                    "message": f"{'Rate limited' if isinstance(exc, RateLimitedError) else 'Temporary LLM error'}, "
                               f"retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})",
                })
            await sleep(delay)
            attempt += 1


# ----------------------------------------------------------------- Groq provider
def _parse_retry_after(exc: Exception) -> float | None:
    try:
        raw = exc.response.headers.get("retry-after")  # type: ignore[attr-defined]
        return float(raw) if raw is not None else None
    except Exception:
        return None


@dataclass
class _ApiKey:
    client: Any
    index: int
    cooldown_until: float = 0.0


class GroqProvider:
    """Groq chat completions backed by a rotating pool of API keys.

    A 429 is scoped to the key that hit it, so instead of sleeping the call is retried
    straight away on the next key that is not cooling down. The error only reaches
    `call_with_retries` once every key is limited, and the backoff then waits for the
    key that frees up soonest.
    """

    def __init__(self, settings: Settings, *, now: Callable[[], float] = time.monotonic):
        import groq  # imported lazily so tests/mock mode don't need the SDK

        pool = settings.groq_key_pool
        if not pool:
            raise RuntimeError(
                "No Groq API key set. Fill GROQ_API_KEY (or a comma-separated GROQ_API_KEYS "
                "pool) in .env, or set MOCK_LLM=true."
            )
        self._groq = groq
        self._now = now
        self._default_cooldown = max(1.0, settings.llm_key_cooldown_s)
        self._cursor = 0
        # max_retries=0: all retry logic lives in call_with_retries so it is visible + testable.
        self._keys = [
            _ApiKey(groq.AsyncGroq(api_key=key, timeout=settings.llm_request_timeout_s, max_retries=0), i)
            for i, key in enumerate(pool)
        ]

    @property
    def key_count(self) -> int:
        return len(self._keys)

    def _order(self) -> list[_ApiKey]:
        """Keys to try for one request, best first."""
        now = self._now()
        ready = [k for k in self._keys if k.cooldown_until <= now]
        if not ready:
            # All cooling down: make one attempt on the key that frees up first rather
            # than burning a request per key; the caller's backoff does the waiting.
            return [min(self._keys, key=lambda k: k.cooldown_until)]
        start, size = self._cursor, len(self._keys)
        self._cursor = (start + 1) % size
        # Round-robin: spread the load so the least recently used key goes first.
        return sorted(ready, key=lambda k: (k.index - start) % size)

    def _cool_down(self, slot: _ApiKey, exc: Exception) -> float:
        """Park a key that just returned 429 for retry-after, else a whole rate window."""
        seconds = _parse_retry_after(exc)
        seconds = self._default_cooldown if seconds is None else max(seconds, 1.0)
        slot.cooldown_until = self._now() + seconds
        return seconds

    async def complete(self, *, agent, model, messages, json_mode, tools, temperature, max_tokens) -> LLMResult:
        g = self._groq
        kwargs: dict[str, Any] = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        # No tools -> send no tool_choice at all. Declaring tool_choice="none" does not stop a
        # tool-trained model from answering with a call, it only guarantees the 400 afterwards.

        waits: list[float] = []
        for slot in self._order():
            try:
                resp = await slot.client.chat.completions.create(**kwargs)
            except g.RateLimitError as e:
                waits.append(self._cool_down(slot, e))
                continue  # per-key limit — use another key instead of sleeping
            except (g.APIConnectionError, g.APITimeoutError) as e:
                raise TransientLLMError(f"connection error: {e}") from e
            except g.BadRequestError as e:
                kind = classify_bad_request(str(e))
                raise kind(f"model produced invalid output: {e}" if kind is LLMOutputError
                           else f"the model called a tool this request does not have: {e}") from e
            except g.APIStatusError as e:
                if e.status_code >= 500:
                    raise TransientLLMError(f"groq {e.status_code}", _parse_retry_after(e)) from e
                raise LLMError(f"groq {e.status_code}: {e}") from e
            return self._to_result(resp, model)

        # Every key we tried was rate limited. Hand the shortest wait to the backoff loop.
        retry_after = min(waits) if waits else None
        if len(self._keys) > 1:
            raise RateLimitedError(retry_after, f"all {len(self._keys)} Groq keys rate limited (429)")
        raise RateLimitedError(retry_after)

    @staticmethod
    def _to_result(resp: Any, model: str) -> LLMResult:
        choice = resp.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        raw_calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
            raw_calls.append({"id": tc.id, "type": "function",
                              "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}})
        raw = {"role": "assistant", "content": msg.content or "", **({"tool_calls": raw_calls} if raw_calls else {})}
        u = resp.usage
        usage = Usage(getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0), getattr(u, "total_tokens", 0)) if u else Usage()
        return LLMResult(msg.content or "", usage, model, calls, raw, choice.finish_reason or "stop")


# ----------------------------------------------------------------- client
class LLMClient:
    def __init__(self, settings: Settings, provider: LLMProvider | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self.settings = settings
        self._sleep = sleep
        if provider is None:
            if settings.mock_llm:
                from app.llm.mock import MockProvider
                provider = MockProvider()
            else:
                provider = GroqProvider(settings)
        self.provider = provider
        self._sem = asyncio.Semaphore(max(1, settings.llm_max_concurrency))

    def model_for(self, kind: str) -> str:
        s = self.settings
        if s.mock_llm:
            return f"mock-{kind}"
        name = {"default": s.groq_model, "fast": s.groq_fast_model or s.groq_model, "vision": s.groq_vision_model}.get(kind, "")
        if not name:
            raise LLMError(f"No model configured for '{kind}'. Set GROQ_MODEL / GROQ_FAST_MODEL / GROQ_VISION_MODEL.")
        return name

    async def chat(
        self, *, agent: str, messages: list[dict], kind: str = "default", json_mode: bool = False,
        tools: list[dict] | None = None, temperature: float = 0.4, max_tokens: int = 2048,
        on_retry: Callable[[dict], Awaitable[None]] | None = None,
    ) -> LLMResult:
        model = self.model_for(kind)
        if json_mode and not any("json" in str(m.get("content", "")).lower() for m in messages):
            messages = [*messages, {"role": "user", "content": "Respond with valid JSON only."}]  # Groq JSON mode requires the word

        async def attempt() -> LLMResult:
            # The semaphore is held only while a request is in flight, NOT while sleeping in backoff.
            async with self._sem:
                return await self.provider.complete(
                    agent=agent, model=model, messages=messages, json_mode=json_mode,
                    tools=tools, temperature=temperature, max_tokens=max_tokens,
                )

        return await call_with_retries(
            attempt, max_retries=self.settings.llm_max_retries, base_delay=self.settings.llm_backoff_base_s,
            max_delay=self.settings.llm_backoff_max_s, on_retry=on_retry, sleep=self._sleep,
        )
