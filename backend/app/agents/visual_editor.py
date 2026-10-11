"""The visual editor's model call: one selected element plus one instruction, answered with one patch.

Nothing in here writes to the workspace. `verify()` in `app/services/visual_edit.py` proves the patch is
real, small and about the element that was clicked; when it is not, the model gets that exact reason back
and one more chance. Two failed attempts is a refusal, not a guess.
"""
from __future__ import annotations

from app.agents.base import AgentOutputError, BaseAgent
from app.agents.schemas import VisualPatch
from app.services import visual_edit
from app.services.workspace_manager import WorkspaceError


class VisualEditorAgent(BaseAgent):
    name = "visual_editor"
    model_kind = "fast"
    temperature = 0.2      # copying a fragment verbatim is precision work, not a creative task
    max_tokens = 900

    async def run(self, ctx) -> str:
        raise NotImplementedError("the visual editor is called per selection, never as a crew step")

    async def patch(self, ctx, *, user: str, texts: dict[str, str], located: dict) -> dict:
        """Ask for a patch and keep only one that survives verification."""
        messages = self.json_messages(user)
        error = ""
        for attempt in (1, 2):
            proposal = await self.json_from(ctx, messages, VisualPatch)
            try:
                return visual_edit.verify(proposal.model_dump(), texts, located)
            except WorkspaceError as exc:
                error = exc.message
                if attempt == 2:
                    break
                messages = self._correction(messages, proposal.model_dump_json(), error)
        raise AgentOutputError(f"visual_editor: no patch that fits this element: {error}")
