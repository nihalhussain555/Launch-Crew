"""FastAPI app: auth, API, agents and SSE in a single service."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (routes_auth, routes_config, routes_projects, routes_runs, routes_share, routes_stats,
                     routes_stream)
from app.config import get_settings
from app.db.mongo import create_client, ensure_indexes
from app.llm.client import LLMClient
from app.orchestrator.runner import fail_stale_runs
from app.tools.file_writer import build_storage
from app.utils.logger import get_logger

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_for_runtime()      # fail fast on missing GROQ_*/JWT_SECRET instead of mid-run
    if settings.app_env == "production" and settings.jwt_secret == "change-me":
        raise RuntimeError("Set a strong JWT_SECRET in production")
    client = create_client(settings)
    app.state.settings = settings
    app.state.db = client[settings.mongo_db]
    app.state.llm = LLMClient(settings)
    app.state.storage = build_storage(settings, app.state.db)   # mongo (default) | local; S3/R2 = new Storage impl
    await ensure_indexes(app.state.db)
    stale = await fail_stale_runs(app.state.db)
    log.info("started (mock_llm=%s, stale runs failed=%s)", settings.mock_llm, stale)
    yield
    client.close()


app = FastAPI(title="Launch Crew API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in (routes_auth.router, routes_config.router, routes_projects.router, routes_runs.router,
          routes_share.router, routes_stats.router, routes_stream.router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"status": "ok"}