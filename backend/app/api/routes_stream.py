"""Server-Sent Events. Events live in MongoDB, so the stream survives reconnects (Last-Event-ID) and multiple workers."""
import asyncio
import json
import time

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.api.routes_runs import own_run
from app.core.deps import get_db, get_user_header_or_query

router = APIRouter(prefix="/api/runs", tags=["stream"])
POLL_S, KEEPALIVE_S, MAX_STREAM_S = 0.5, 15, 60 * 30
FINAL = {"deployed", "failed"}


def sse(event: dict) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event['data'], default=str)}\n\n"


@router.get("/{run_id}/stream")
async def stream(run_id: str, request: Request, last_event_id: str | None = Header(default=None),
                 db=Depends(get_db), user=Depends(get_user_header_or_query)):
    await own_run(db, run_id, user)
    user_run_id = ObjectId(run_id)
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def gen():
        nonlocal after
        started = last_ping = time.monotonic()
        yield "retry: 3000\n\n"
        while time.monotonic() - started < MAX_STREAM_S:
            if await request.is_disconnected():
                return
            events = [e async for e in db.run_events.find({"run_id": run_id, "seq": {"$gt": after}}).sort("seq", 1).limit(100)]
            for e in events:
                after = e["seq"]
                yield sse(e)
                if e["type"] in FINAL:
                    return
            if not events:
                run = await db.runs.find_one({"_id": user_run_id}, {"status": 1})
                if run and run["status"] in FINAL:      # finished and everything already delivered
                    return
                if time.monotonic() - last_ping > KEEPALIVE_S:
                    last_ping = time.monotonic()
                    yield ": keepalive\n\n"
            await asyncio.sleep(POLL_S)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
