"""Shared run state + RunContext (guardrails: step cap, token budget; event emission; checkpoints)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.agents.schemas import CopyDoc, Design, MarketBrief, Strategy


class GuardrailError(Exception):
    """A configured guardrail (steps / tokens / timeout) stopped the run."""


class BudgetExceeded(GuardrailError):
    pass


class StepLimitExceeded(GuardrailError):
    pass


class RunState(BaseModel):
    """Everything agents share. Persisted to Mongo (except `html`, which lives in the storage layer)."""
    idea: str
    brief: MarketBrief | None = None
    strategy: Strategy | None = None
    content: CopyDoc | None = None
    design: Design | None = None

    html: str | None = None
    html_key: str | None = None
    html_version: int = 0
    sanitizer_violations: list[str] = Field(default_factory=list)

    iteration: int = 0
    check_results: list[dict] = Field(default_factory=list)
    check_summary: dict = Field(default_factory=dict)
    critic_feedback: dict | None = None
    critic_history: list[dict] = Field(default_factory=list)
    pending_fixes: dict[str, list[str]] = Field(default_factory=dict)
    screenshot_keys: dict[str, str] = Field(default_factory=dict)

    social_posts: list[dict] = Field(default_factory=list)
    email: dict | None = None
    deploy_url: str | None = None
    deploy_mock: bool = False

    def persisted(self) -> dict:
        return self.model_dump(exclude={"html"})


Sink = Callable[[str, dict], Awaitable[None]]
Checkpoint = Callable[["RunContext", "str | None"], Awaitable[None]]


class RunContext:
    def __init__(self, *, run_id: str, settings, llm, state: RunState, sink: Sink, storage,
                 checkpoint: Checkpoint | None = None, tokens_used: int = 0, steps: int = 0):
        self.run_id, self.settings, self.llm, self.state = run_id, settings, llm, state
        self.storage, self._sink, self._checkpoint = storage, sink, checkpoint
        self.tokens_used, self.steps = tokens_used, steps

    async def emit(self, type_: str, **data: Any) -> None:
        await self._sink(type_, data)

    async def checkpoint(self, status: str | None = None) -> None:
        if self._checkpoint:
            await self._checkpoint(self, status)

    # ---- guardrails
    def check_budget(self) -> None:
        if self.tokens_used >= self.settings.max_token_budget:
            raise BudgetExceeded(f"Token budget exhausted ({self.tokens_used}/{self.settings.max_token_budget})")

    def add_tokens(self, usage) -> None:
        self.tokens_used += usage.total_tokens
        self.check_budget()

    def next_step(self, agent: str) -> None:
        self.steps += 1
        if self.steps > self.settings.max_steps:
            raise StepLimitExceeded(f"Step limit reached ({self.settings.max_steps}) before '{agent}' could run")
