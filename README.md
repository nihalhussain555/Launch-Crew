# 🚀 Launch Crew

Type one product idea. A crew of AI agents researches it, writes copy, designs and builds a landing page, **tests its own work in a real browser**, and deploys only after **you** approve.

```
                         ┌────────────────────────────── Render (Docker) ──────────────────────────────┐
 Browser                 │  FastAPI  (auth · API · SSE)                                                │
 React + Vite  ──HTTPS──▶│    │                                                                        │
 (Vercel)      ◀──SSE────│    ▼                                                                        │
                         │  Orchestrator ─▶ Researcher ─▶ Strategist ─▶ Copywriter ─▶ Designer         │
                         │       │                                                         │            │
                         │       │            ┌── fixes ◀── Critic ◀── Playwright ◀── Engineer ◀──┘     │
                         │       │            └────────────▶ (max MAX_CRITIC_ITERATIONS)               │
                         │       ▼                                                                      │
                         │  ⛔ awaiting_approval ──(you click Approve)──▶ Launcher ─▶ Netlify           │
                         └──────┬───────────────────────┬──────────────────────────┬───────────────────┘
                                ▼                       ▼                          ▼
                         MongoDB Atlas            Groq API / Tavily          Artifact storage
                    (users, projects, runs,       (LLM + web search)      (local disk; S3/R2 swappable)
                     events, state)
```

Two services only: `client/` (React, Vercel) and `backend/` (FastAPI, Render). No Node server.

## Quick start (no API keys needed)

```bash
cp backend/.env.example backend/.env      # MOCK_LLM=true by default
cp frontend/.env.example frontend/.env
docker compose up --build
```
Open http://localhost:5173, sign up, type an idea. The mock LLM produces a full run (including the real Playwright checks and the approval gate); deploys are simulated and labelled as such.

### Without Docker
```bash
# backend (needs Python 3.10-3.12)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install --with-deps chromium
cp .env.example .env     # set MONGO_URI=mock:// (in-memory) or mongodb://localhost:27017
uvicorn app.main:app --reload
# client
cd frontend && npm install && npm run dev
```
Tests: `cd backend && pytest` (Chromium tests auto-skip if the browser isn't installed).

## Environment variables (backend)

| Var | Purpose | Default |
|---|---|---|
| `MOCK_LLM` | Run the whole flow offline with canned agent output | `false` |
| `GROQ_API_KEY` | Single Groq key (backend only) | – |
| `GROQ_API_KEYS` | Comma-separated pool of Groq keys; the client rotates between them and cools down any key that returns 429 | – |
| `GROQ_MODEL` | Default model (Researcher, Copywriter, Engineer, Critic) | – (see `.env.example`) |
| `GROQ_FAST_MODEL` | Cheaper model (Strategist, Designer, Launcher); falls back to `GROQ_MODEL` | – |
| `GROQ_VISION_MODEL` | Optional: enables an advisory visual review of the mobile screenshot | empty |
| `LLM_MAX_CONCURRENCY` | Simultaneous in-flight LLM calls (semaphore) | `2` |
| `LLM_MAX_RETRIES` | Retries on 429 / 5xx / connection errors | `5` |
| `LLM_KEY_COOLDOWN_S` | How long a key stays parked after a 429 with no `retry-after` | `60` |
| `TAVILY_API_KEY` | Real web search (empty → mock search) | – |
| `NETLIFY_AUTH_TOKEN` | Real deploys (empty → simulated URL, flagged in UI) | – |
| `MONGO_URI` / `MONGO_DB` | MongoDB connection (`mock://` = in-memory, dev only) | `mongodb://localhost:27017` / `launch_crew` |
| `JWT_SECRET` | **Set a long random value in production** | – |
| `ALLOWED_ORIGIN` | CORS origin(s), comma-separated | `http://localhost:5173` |
| `MAX_STEPS` | Max agent executions per run | `30` |
| `MAX_TOKEN_BUDGET` | Max total tokens per run | `120000` |
| `AGENT_TIMEOUT_S` | Per-agent timeout | `120` |
| `MAX_CRITIC_ITERATIONS` | Max Critic reviews (hard cap on the fix loop) | `3` |
| `TOOL_ROUNDS_CAP` | Max tool-calling rounds for the Researcher | `3` |
| `RUNS_PER_HOUR` | Per-user run-creation limit | `10` |
| `STORAGE_DIR` | Where HTML/screenshots are stored | `/data/artifacts` |

Client: `frontend/.env` → `VITE_API_URL` — the backend URL, baked in at build time. It must match one of the origins listed in the backend's `ALLOWED_ORIGIN`, or every call is blocked by CORS. Only public values belong there: the bundle is readable by any visitor.

## Deploy

1. **MongoDB Atlas** – create a free cluster, a DB user, and allow Render's outbound IPs (or `0.0.0.0/0` while testing). Copy the SRV connection string.
2. **Render** – New → Blueprint → select this repo (uses `render.yaml`). Fill the `sync: false` secrets: `MONGO_URI`, `GROQ_*`, optional `TAVILY_API_KEY`, `NETLIFY_AUTH_TOKEN`, and `ALLOWED_ORIGIN` (your Vercel URL, set after step 3). Use at least the *Starter* plan: Chromium needs more than 512 MB.
3. **Vercel** – import the repo, set **Root Directory = `client`**, add env `VITE_API_URL=https://<your-render-service>.onrender.com`. `vercel.json` already contains the SPA rewrite.
4. Go back to Render and set `ALLOWED_ORIGIN` to the Vercel URL, then redeploy.

## Groq notes

- **Model names change.** None are hardcoded in code; set `GROQ_MODEL` / `GROQ_FAST_MODEL` / `GROQ_VISION_MODEL` from Groq's current model list (https://console.groq.com/docs/models). The values in `.env.example` are only examples.
- **Rate limits.** On HTTP 429 the client honours the `retry-after` header, otherwise uses exponential backoff with jitter. Each retry shows up in the UI trace as "Rate limited — retrying". Lower `LLM_MAX_CONCURRENCY` if you hit tokens-per-minute limits often.
- **Several keys, one pool.** `GROQ_API_KEYS` takes a comma-separated list (merged with `GROQ_API_KEY`, deduplicated). A 429 is per-key, so the client parks that key for `retry-after` (or `LLM_KEY_COOLDOWN_S` when the header is missing) and immediately retries the same request on the next key instead of sleeping — a run only waits when *every* key is limited, and then only for the shortest remaining wait. Keys are used round-robin, so the load spreads evenly. Raise `LLM_MAX_CONCURRENCY` to roughly the number of keys, otherwise the semaphore, not the quota, is the bottleneck.
- **Token efficiency.** Agents receive only the fields they need (not the history); the Researcher's tool chatter is collapsed before the structured call; the Critic only calls the LLM when a check failed.
- JSON mode is used for structured agents; output is Pydantic-validated with one corrective retry. The Engineer returns raw HTML (JSON-escaping a whole page is fragile) which is sanitized and structurally checked.

## Guardrails

Max steps · max token budget · per-agent timeout · Critic iteration cap · human approval before deploy (atomic `awaiting_approval → deploying` transition, so no double/forged deploys) · Pydantic validation + retry on every agent · HTML sanitizer (no external scripts/links/images/fonts, no network calls, forms neutralised, CSP meta injected) · sandboxed preview iframe · API keys backend-only · per-user run rate limit · runs interrupted by a restart are marked failed.

## Project layout

```
backend/app/{main,config}.py  core/ (jwt, bcrypt, deps, rate limit)  db/  llm/ (client, mock)  api/
agents/ (one per agent + schemas)  orchestrator/ (graph, state, runner)  tools/ (search, browser_checks,
sanitizer, deploy, file_writer)  prompts/*.md  tests/        client/src/{pages,components,hooks,api.js}
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI says "Cannot reach the server" | Check `VITE_API_URL`, that the backend is up (`/health`), and `ALLOWED_ORIGIN` matches the client origin exactly (no trailing slash). |
| Run fails: "No model configured" | Set `GROQ_MODEL` (and `GROQ_FAST_MODEL`) or `MOCK_LLM=true`. |
| Frequent "Rate limited — retrying" | Lower `LLM_MAX_CONCURRENCY`, use a smaller `GROQ_FAST_MODEL`, or upgrade your Groq tier. |
| "Could not launch Chromium" | Use the provided Dockerfile (Playwright image). Keep `playwright` in `requirements.txt` identical to the image tag. Locally: `playwright install --with-deps chromium`. |
| Chromium crashes in Docker | Give the container more shared memory (`shm_size: 1gb`) / RAM. |
| Previews/screenshots vanish after redeploy | Attach a persistent disk (see `render.yaml`) or implement `Storage` for S3/R2. |
| Run stuck / failed with "Server restarted…" | The backend restarted mid-run; start a new run. |
| Mongo connection errors on Atlas | Allow the host's IP in Atlas Network Access; verify the SRV string/password encoding. |

## Notes

- The Playwright base image ships Python 3.12 (there is no official 3.11 variant); the code runs on 3.10-3.12.
- SSE auth: browsers' `EventSource` can't set headers, so **only** `/api/runs/{id}/stream` also accepts `?token=`.
