import asyncio

import pytest

from app.llm.client import (LLMClient, LLMResult, RateLimitedError, TransientLLMError, Usage, call_with_retries,
                            compute_backoff)
from tests.conftest import make_settings


def test_backoff_honours_retry_after():
    d = compute_backoff(0, 7.0, rng=lambda: 0.0)
    assert d == 7.0
    assert 7.0 <= compute_backoff(0, 7.0, rng=lambda: 1.0) <= 7.5


def test_backoff_exponential_with_jitter_and_cap():
    lo = [compute_backoff(a, None, base=1, cap=30, rng=lambda: 0.0) for a in range(8)]
    hi = [compute_backoff(a, None, base=1, cap=30, rng=lambda: 1.0) for a in range(8)]
    assert lo[:3] == [0.5, 1.0, 2.0] and hi[:3] == [1.0, 2.0, 4.0]
    assert max(hi) == 30 and all(l <= h for l, h in zip(lo, hi))


async def test_retries_then_succeeds_and_reports_events():
    calls, events, sleeps = {"n": 0}, [], []

    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitedError(2.0)
        return "ok"

    async def on_retry(info): events.append(info)
    async def sleep(s): sleeps.append(s)

    assert await call_with_retries(fn, max_retries=5, on_retry=on_retry, sleep=sleep, rng=lambda: 0.0) == "ok"
    assert calls["n"] == 3 and sleeps == [2.0, 2.0]
    assert events[0]["reason"] == "rate_limited" and "retrying" in events[0]["message"]


async def test_gives_up_after_max_retries():
    async def fn(): raise TransientLLMError("boom")
    async def sleep(s): pass
    with pytest.raises(TransientLLMError):
        await call_with_retries(fn, max_retries=2, sleep=sleep)


async def test_non_retryable_error_not_retried():
    n = {"c": 0}
    async def fn():
        n["c"] += 1
        raise ValueError("nope")
    with pytest.raises(ValueError):
        await call_with_retries(fn, max_retries=3)
    assert n["c"] == 1


async def test_semaphore_limits_concurrency():
    state = {"cur": 0, "max": 0}

    class Slow:
        async def complete(self, **kw):
            state["cur"] += 1; state["max"] = max(state["max"], state["cur"])
            await asyncio.sleep(0.02)
            state["cur"] -= 1
            return LLMResult("{}", Usage(1, 1, 2))

    client = LLMClient(make_settings(llm_max_concurrency=2), provider=Slow())
    await asyncio.gather(*[client.chat(agent="x", messages=[{"role": "user", "content": "hi"}]) for _ in range(8)])
    assert state["max"] == 2


async def test_client_retries_provider_429():
    attempts = {"n": 0}

    class Flaky:
        async def complete(self, **kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RateLimitedError(0.0)
            return LLMResult("{}", Usage(1, 1, 2))

    seen = []
    async def sleep(s): pass
    client = LLMClient(make_settings(), provider=Flaky(), sleep=sleep)
    async def on_retry(i): seen.append(i)
    res = await client.chat(agent="x", messages=[{"role": "user", "content": "hi"}], on_retry=on_retry)
    assert res.text == "{}" and attempts["n"] == 2 and len(seen) == 1
