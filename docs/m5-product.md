# Milestone 5 — Make it a product

Deep Search Module 12 / Lab 12 · Production RAG Modules 04, 12, 13

## Goal

A reviewer who has never seen the code can assess a vendor from the UI, read why each verdict was given, send vendor questions, and record a decision that **survives a server restart**.

## Architecture

```
UI (Streamlit) ──HTTP──► FastAPI
                           │
                           ├─ POST /assess ──► Redis+RQ (or inline thread)
                           │                      │
                           │                      ▼
                           │                 worker: LangGraph + SqliteSaver
                           │                 interrupt() at human_gate
                           │
                           ├─ GET /jobs/{id}  (poll status / trace / timings)
                           ├─ POST /approve/{id}  → Command(resume=…)
                           ├─ GET /vendors/{name}/history
                           └─ GET /observability  (last 20 · p50/p95)
                                    │
                                    ▼
                              Postgres or SQLite assessments table
```

## Run locally (no Docker)

```bash
pip install -r requirements.txt
pip install fastapi "uvicorn[standard]" streamlit redis rq "psycopg[binary]" langgraph-checkpoint-sqlite httpx

# Terminal 1 — API (inline queue if Redis is down)
set VRA_INLINE_QUEUE=1
set LLM_PROVIDER=mock
set SEARCH_PROVIDER=offline
uvicorn app.api:app --reload --port 8000

# Terminal 2 — UI
set VRA_API_BASE=http://127.0.0.1:8000
streamlit run app/ui.py
```

Sign in as `reviewer` in the sidebar → **Assess** → wait until `awaiting_approval` → **Reject** or **Approve** (Approve hidden when overall is BLOCKED).

## Cloud Redis + Postgres (Neon + Upstash)

The API already reads cloud URLs from `.env` — no code change needed beyond TLS helpers.

1. **Neon** ([neon.tech](https://neon.tech)) → create a project → copy the connection string:
   ```env
   DATABASE_URL=postgresql://USER:PASS@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require
   ```
   If you omit `sslmode`, the app adds `sslmode=require` automatically for non-localhost hosts.

2. **Upstash** ([upstash.com](https://upstash.com)) → create Redis → copy the **TLS** URL:
   ```env
   REDIS_URL=rediss://default:TOKEN@xxxx.upstash.io:6379
   ```
   A plain `redis://…upstash.io…` URL is upgraded to `rediss://` automatically.

3. Turn off the in-process fallback and point both API + worker at the same env:
   ```env
   VRA_INLINE_QUEUE=0
   QUEUE_NAME=assess
   ```

4. Verify connectivity (does not print secrets):
   ```bash
   python scripts/m5_cloud_smoke.py
   ```

5. Run locally against the cloud stores:
   ```bash
   # Terminal 1
   uvicorn app.api:app --port 8000
   # Terminal 2
   python -m app.worker
   # Terminal 3
   streamlit run app/ui.py
   ```

6. `GET http://127.0.0.1:8000/health` should show `redis: true`, `queue: "rq"`, and a `store` host that is not localhost.

Docker Compose remains optional for fully local Redis/Postgres.

## Env reference

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Neon/Postgres URL; empty → SQLite `data/assessor.db` |
| `REDIS_URL` | Upstash/Redis URL (`rediss://` for TLS); unreachable → in-process thread |
| `VRA_INLINE_QUEUE=0` | Use Redis+RQ (`1` = in-process for tests/demo) |
| `VRA_CHECKPOINT_PATH` | LangGraph SqliteSaver file (local; pause/resume on one machine) |
| `X-User-Id` | Identity header → server-side ACL groups |

## ACL

`user_groups` are **never** taken from the request body. `app/auth.py` maps `X-User-Id` → groups (`alice` / `bob` / `reviewer` / …). Unknown users get `["public"]` only.

## Human gate

- Assessment path sets `await_human=True`.
- `human_gate` calls LangGraph `interrupt()` until `/approve/{run_id}` resumes with `Command(resume={decision, approver, comment})`.
- Checkpoints live in SQLite (`VRA_CHECKPOINT_PATH`); assessment rows live in Postgres/SQLite.
- **BLOCKED** assessments cannot be approved (API 409 + UI hides Approve).

## Observability

`GET /observability` returns the last 20 runs with **p50/p95** duration and cost, plus per-stage timing rollups (Lab 13 style). Each run also stores `stage_timings` on the assessment row and in `runs/<id>/stage_timings.json`.

## Tests

```bash
python -m pytest tests/test_m5_product.py -q
```
