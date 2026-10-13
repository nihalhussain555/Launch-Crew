"""The IDE assistant's model call: a plain-English request over the run's own files, answered with edits.

One call, up to two attempts. `app/services/ide_assistant.py` shows the model the stored text and checks
each returned change against it; when a change does not match, the model gets that exact reason back and
one more chance. Two failed attempts is a 502 with the reason, not a guessed patch.
"""
from __future__ import annotations

from app.agents.base import AgentOutputError, BaseAgent
from app.agents.schemas import IdePatchSet
from app.services import ide_assistant
from app.services.workspace_manager import WorkspaceError


class IdeAssistantAgent(BaseAgent):
    name = "ide_assistant"
    model_kind = "fast"
    temperature = 0.2      # copying a fragment verbatim is precision work, not a creative task
    max_tokens = 2000

    async def run(self, ctx) -> str:
        raise NotImplementedError("the assistant is called per request, never as a crew step")

    async def patch(self, ctx, *, user: str, texts: dict[str, str], allowed: list[str] | None = None) -> dict:
        """Ask for a change set and keep only one that survives verification against the stored files."""
        messages = self.json_messages(user)
        error = ""
        for attempt in (1, 2):
            proposal = await self.json_from(ctx, messages, IdePatchSet)
            try:
                return ide_assistant.verify(proposal.model_dump(), texts, allowed=allowed)
            except WorkspaceError as exc:
                error = exc.message
                if attempt == 2:
                    break
                messages = self._correction(messages, proposal.model_dump_json(), error)
        raise AgentOutputError(f"ide_assistant: no edit that fits these files: {error}")
