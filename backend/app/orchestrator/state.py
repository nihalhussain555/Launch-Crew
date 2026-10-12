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
    # What the creation wizard collected (app/agents/schemas.SiteSpec): business type, audience, pages,
    # preferred style and colour, desired features. Empty for runs created before the wizard existed.
    spec: dict = Field(default_factory=dict)
    brief: MarketBrief | None = None
    strategy: Strategy | None = None
    content: CopyDoc | None = None
    design: Design | None = None
    # This run's design direction (app/agents/variants): hero shape, nav, section order, motif, palette.
    style: dict = Field(default_factory=dict)

    html: str | None = None
    html_key: str | None = None
    html_version: int = 0
    sanitizer_violations: list[str] = Field(default_factory=list)

    # Workspace: every build is published as a file set plus a restorable snapshot (app/tools/splitter).
    files: list[dict] = Field(default_factory=list)       # [{name, language, key, bytes, note}]
    # Source a feature build wrote for the user to run themselves (app/services/feature_build.py): the
    # page stays canonical for preview, share and deploy, and these extra files ride along with it -
    # re-attached on every publish so a crew rebuild never deletes someone's server code, and snapshotted
    # with the rest of the file set so a workspace restore puts them back as they were.
    authored_files: list[dict] = Field(default_factory=list)   # [{name, language, key, bytes, note, source}]
    versions: list[dict] = Field(default_factory=list)    # [{v, key, bytes, at, note, errors, readiness}]
    chat: list[dict] = Field(default_factory=list)        # [{role, text, at, target, version}]
    note: str = ""                                        # what the next snapshot should be labelled with

    # File-level editing (app/services/workspace_manager.py): whole-file-set snapshots and change plans.
    workspace_versions: list[dict] = Field(default_factory=list)  # [{w, at, note, label, cause, html_version, files, changed}]
    change_plans: list[dict] = Field(default_factory=list)        # [{id, at, request, status, changes, impact, result}]
    # Proposals from the visual editor (app/services/visual_edit.py): one selected element, one patch,
    # waiting to be reviewed. [{id, at, status, instruction, element, source, patch, plan, version, result}]
    visual_edits: list[dict] = Field(default_factory=list)
    # Proposals from the theme customizer (app/services/theme_edit.py): one token patch for the whole
    # page, waiting to be reviewed. [{id, at, status, theme, summary, changes, reaches, plan, version, result}]
    theme_edits: list[dict] = Field(default_factory=list)
    # Proposals from a plain-English feature request (app/services/feature_build.py): the page block that
    # adds the panels, plus the source files that ride with it. [{id, at, status, keys, features, files,
    # changes, summary, warnings, plan, version, result}] - the record is the report, so it says what each
    # surface of each capability actually reached.
    feature_edits: list[dict] = Field(default_factory=list)
    # The undo/redo timeline, as snapshot numbers: each entry is a whole file set a step would restore.
    undo_stack: list[int] = Field(default_factory=list)
    redo_stack: list[int] = Field(default_factory=list)
    impact: dict | None = None                            # the last impact report measured before editing
    changed_files: dict | None = None                     # per-file line movement of the last applied change
    validation: dict | None = None                        # how the last change fared after the checks re-ran

    iteration: int = 0
    revisions: int = 0
    panel: dict | None = None
    readiness: dict | None = None
    check_results: list[dict] = Field(default_factory=list)
    check_summary: dict = Field(default_factory=dict)
    critic_feedback: dict | None = None
    critic_history: list[dict] = Field(default_factory=list)
    pending_fixes: dict[str, list[str]] = Field(default_factory=dict)
    screenshot_keys: dict[str, str] = Field(default_factory=dict)

    # On-demand audits (app/agents/audits.py): each report records the html_version it measured.
    audits: dict[str, dict] = Field(default_factory=dict)
    tests: dict | None = None                                 # generated suite + the result of running it

    social_posts: list[dict] = Field(default_factory=list)
    email: dict | None = None
    deploy_url: str | None = None
    deploy_mock: bool = False
    deploy_warning: str | None = None                         # what a visitor gets that the user did not

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
