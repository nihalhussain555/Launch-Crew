"""Stopping a run that is in flight: one in-process signal, one flag on the run document.

The crew runs as a background task inside this process, so a Stop that lands here can cut into the agent
step that is currently waiting for the model - that is the fast path, and it is what makes the button feel
like a button. The flag on the run is what covers the cases the event cannot reach: a second worker, or a
run this process did not start. It is read at every agent boundary rather than every token, so a stop costs
at most the step already in flight and never a half-written page.

Nothing here throws away work. State is checkpointed after each step, so a stopped run keeps the research,
copy, design and page versions it had already reached, and says so in the run's own event stream.
"""
from __future__ import annotations

import asyncio

from bson import ObjectId

# run_id -> the event the pipeline that is running it armed. Only one pipeline per run at a time: every
# follow-up phase claims the run through runner.claim_for_revision first, which cannot happen twice.
_SIGNALS: dict[str, asyncio.Event] = {}


def arm(run_id: str) -> asyncio.Event:
    """Start a stop watch for this run's pipeline. Returns the event the step waits on."""
    event = asyncio.Event()
    _SIGNALS[run_id] = event
    return event


def disarm(run_id: str) -> None:
    """End of the pipeline: stop listening, so a later phase cannot be killed by an old stop."""
    _SIGNALS.pop(run_id, None)


def wake(run_id: str) -> bool:
    """Say so now, in this process. False when the run is building somewhere else."""
    event = _SIGNALS.get(run_id)
    if event is None:
        return False
    event.set()
    return True


async def requested(db, run_id: str) -> bool:
    """The durable half of the signal: the flag the stop endpoint wrote on the run."""
    if not ObjectId.is_valid(run_id):
        return False
    doc = await db.runs.find_one({"_id": ObjectId(run_id)}, projection={"cancel_requested": 1})
    return bool(doc and doc.get("cancel_requested"))


async def clear(db, run_id: str) -> None:
    """Forget a stop once its effect has been recorded, so the next phase starts clean."""
    if not ObjectId.is_valid(run_id):
        return
    await db.runs.update_one({"_id": ObjectId(run_id)}, {"$set": {"cancel_requested": False}})
