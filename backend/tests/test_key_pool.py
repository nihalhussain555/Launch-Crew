"""Groq key pooling: a 429 cools down one key and the request moves to the next one."""
import sys
import types
from types import SimpleNamespace

import pytest

from app.llm.client import GroqProvider, RateLimitedError
from tests.conftest import make_settings


class FakeRateLimit(Exception):
    def __init__(self, retry_after=None):
        super().__init__("429")
        headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
        self.response = SimpleNamespace(headers=headers)


class FakeStatusError(Exception):
    def __init__(self, status_code=503):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


@pytest.fixture
def fake_groq(monkeypatch):
    """Install a stand-in `groq` module so the provider never touches the network."""
    created: list[FakeClient] = []

    class FakeClient:
        def __init__(self, api_key, **kwargs):
            self.api_key = api_key
            self.init_kwargs = kwargs
            self.errors: list[Exception] = []
            self.calls = 0
            created.append(self)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _create(self, **kwargs):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=f"from:{self.api_key}", tool_calls=None),
                    finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            )

    module = types.ModuleType("groq")
    module.AsyncGroq = FakeClient
    module.RateLimitError = FakeRateLimit
    module.APIConnectionError = ConnectionError
    module.APITimeoutError = TimeoutError
    module.BadRequestError = ValueError
    module.APIStatusError = FakeStatusError
    monkeypatch.setitem(sys.modules, "groq", module)
    return created


class Clock:
    """Manually advancing clock, so cooldown behaviour is deterministic."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def build(keys, fake_groq, **settings_kw):
    settings = make_settings(mock_llm=False, groq_api_keys=keys, groq_model="m", **settings_kw)
    clock = Clock()
    return GroqProvider(settings, now=clock), clock, fake_groq


async def call(p, agent="designer"):
    return await p.complete(agent=agent, model="m", messages=[], json_mode=False,
                            tools=None, temperature=0.5, max_tokens=100)


def test_one_client_per_key_and_sdk_retries_disabled(fake_groq):
    p, _, clients = build("k1", fake_groq)
    assert p.key_count == 1
    assert clients[0].init_kwargs["max_retries"] == 0  # all retrying stays in call_with_retries


async def test_429_on_one_key_moves_to_the_next_without_sleeping(fake_groq):
    p, _, clients = build("k1,k2", fake_groq)
    clients[0].errors.append(FakeRateLimit(45))
    res = await call(p, agent="copywriter")
    assert res.text == "from:k2"
    assert (clients[0].calls, clients[1].calls) == (1, 1)
    assert res.usage.total_tokens == 3


async def test_load_spreads_round_robin_across_keys(fake_groq):
    p, _, clients = build("k1,k2,k3", fake_groq)
    for _ in range(3):
        await call(p)
    assert [c.calls for c in clients] == [1, 1, 1]


async def test_limited_key_is_cooled_down_and_skipped_until_it_recovers(fake_groq):
    p, clock, clients = build("k1,k2", fake_groq)
    clients[0].errors.append(FakeRateLimit(20))
    await call(p)
    await call(p, agent="engineer")
    assert (clients[0].calls, clients[1].calls) == (1, 2)  # k1 is still cooling down
    clock.advance(20)
    await call(p, agent="critic")
    assert clients[0].calls == 2  # released, and it is the least recently used key


async def test_all_keys_limited_raises_with_the_shortest_wait(fake_groq):
    p, _, clients = build("k1,k2", fake_groq)
    clients[0].errors.append(FakeRateLimit(50))
    clients[1].errors.append(FakeRateLimit(9))
    with pytest.raises(RateLimitedError) as exc:
        await call(p)
    assert exc.value.retry_after == 9  # wait for one key, not the sum of all of them
    assert "rate limited" in str(exc.value)
    assert (clients[0].calls, clients[1].calls) == (1, 1)


async def test_429_without_retry_after_uses_the_configured_cooldown(fake_groq):
    p, clock, clients = build("k1,k2", fake_groq, llm_key_cooldown_s=5)
    clients[0].errors.append(FakeRateLimit(None))
    await call(p)
    await call(p)
    assert clients[0].calls == 1
    clock.advance(5)
    await call(p)
    assert clients[0].calls == 2


async def test_non_key_errors_are_not_retried_on_other_keys(fake_groq):
    p, _, clients = build("k1,k2", fake_groq)
    clients[0].errors.append(FakeStatusError(503))
    with pytest.raises(Exception):
        await call(p)
    assert clients[1].calls == 0


def test_missing_key_gives_a_clear_error(fake_groq):
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        GroqProvider(make_settings(mock_llm=False, groq_api_key="", groq_api_keys="", groq_model="m"))


def test_key_pool_merges_dedupes_and_keeps_order():
    s = make_settings(groq_api_key="k1", groq_api_keys=" k2 , k1 ,,k3 ")
    assert s.groq_key_pool == ["k1", "k2", "k3"]


def test_runtime_validation_accepts_a_pool_only():
    make_settings(mock_llm=False, groq_api_key="", groq_api_keys="k1,k2", groq_model="m").validate_for_runtime()
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        make_settings(mock_llm=False, groq_api_key="", groq_api_keys="", groq_model="m").validate_for_runtime()
