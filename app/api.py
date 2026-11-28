"""
app/api.py — the assessor as a web service (FastAPI).

COURSE MAP  Production RAG Modules 04 / 12 / 13 — queued jobs, ACL from identity, observability.

Run:
  uvicorn app.api:app --reload --port 8000
  # optional: rq worker assess   (or VRA_INLINE_QUEUE=1 for in-process jobs)

Endpoints
  POST /assess              → 202 {job_id, run_id, status}  (queued; poll GET /jobs/{id})
  GET  /jobs/{run_id}       → status + partial/full report
  POST /approve/{run_id}    → resume LangGraph interrupt; decision survives restart
  GET  /vendors/{name}/history
  GET  /observability       → last 20 runs + p50/p95 latency & cost
  POST /ask                 → policy Q&A (groups from X-User-Id, never from body)
  GET  /health
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from assessor.config import RUNS_DIR, SETTINGS
from assessor.graph import Pipeline, new_state
from assessor.tracing import Budget, Tracer

from . import db, settings
from .auth import groups_for_user, require_reviewer, require_user
from .worker import resume_assessment_job, run_assessment_job

app = FastAPI(
    title="Nimbu Mart Vendor Risk Assessor",
    version="0.5.0",
    description="Capstone M5 — queued assessments, durable human gate, ACL from identity.",
)


class AskBody(BaseModel):
    question: str
    # user_groups intentionally omitted from the public contract — derived from X-User-Id.


class AssessBody(BaseModel):
    question: str
    vendor: str
    official_domain: Optional[str] = None
    tier: str = "T3"
    users: int = 1
    requested_by: str = "api"


class ApproveBody(BaseModel):
    decision: str  # approve | reject
    approver: str
    comment: str = ""


def _redis():
    """Cloud-safe Redis client (supports rediss:// for Upstash TLS)."""
    from redis import Redis

    from .settings import normalize_redis_url

    url = normalize_redis_url(settings.REDIS_URL)
    # ssl_cert_reqs=None keeps Upstash simple on Windows; URL still uses rediss://
    kwargs = {"decode_responses": False}
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = None
    return Redis.from_url(url, **kwargs)


def _queue():
    if settings.FORCE_INLINE_QUEUE:
        return None
    try:
        from rq import Queue

        conn = _redis()
        conn.ping()
        return Queue(settings.QUEUE_NAME, connection=conn)
    except Exception:
        return None


def _enqueue_assess(payload: dict) -> None:
    q = _queue()
    if q is None:
        # In-process fallback (tests / no Redis): background thread.
        threading.Thread(target=run_assessment_job, args=(payload,), daemon=True).start()
        return
    from rq import Retry

    q.enqueue(run_assessment_job, payload, job_timeout=900, retry=Retry(max=3, interval=[10, 30, 60]),
              job_id=payload["run_id"])


@app.on_event("startup")
def _startup() -> None:
    db.migrate()


@app.get("/health")
def health():
    redis_ok = False
    redis_err = None
    try:
        _redis().ping()
        redis_ok = True
    except Exception as exc:  # noqa: BLE001
        redis_err = str(exc)[:160]
    store = db.backend_name()
    return {
        "ok": True,
        "llm_provider": SETTINGS.llm_provider,
        "search_provider": SETTINGS.search_provider,
        "store": store,
        "redis": redis_ok,
        "redis_error": redis_err,
        "queue": "rq" if redis_ok and not settings.FORCE_INLINE_QUEUE else "inline",
        "cloud_postgres": store.startswith("postgres://") and "localhost" not in store,
    }


@app.post("/ask")
def ask(body: AskBody, identity: tuple[str, list[str]] = Depends(require_user)):
    user_id, groups = identity
    pipe = Pipeline(tracer=None)
    s = pipe.run_plain(new_state(body.question, user_groups=groups, requested_by=user_id))
    if s["route"] == "assessment":
        raise HTTPException(400, "This question needs a full assessment: call POST /assess with vendor, tier and users.")
    return {
        "route": s["route"],
        "answer": s["answer"],
        "user": user_id,
        "user_groups": groups,
        "citations": [c.model_dump() for c in (s["policy_answer"].citations if s.get("policy_answer") else [])],
    }


@app.post("/assess", status_code=202)
def assess(body: AssessBody, identity: tuple[str, list[str]] = Depends(require_user)):
    user_id, groups = identity
    run_id = f"{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:10]}-assess"
    thread_id = run_id
    payload = {
        "run_id": run_id,
        "thread_id": thread_id,
        "question": body.question,
        "vendor": body.vendor,
        "official_domain": body.official_domain,
        "tier": body.tier,
        "users": body.users,
        "requested_by": body.requested_by or user_id,
        "user_groups": groups,
    }
    db.upsert_assessment(
        run_id=run_id, thread_id=thread_id, vendor=body.vendor, question=body.question,
        tier=body.tier, users=body.users, status="queued",
        requested_by=payload["requested_by"], user_groups=groups,
    )
    _enqueue_assess(payload)
    return {"job_id": run_id, "run_id": run_id, "status": "queued", "user": user_id, "user_groups": groups}


@app.get("/jobs/{run_id}")
def job_status(run_id: str):
    row = db.get_assessment(run_id)
    if not row:
        # Fall back to filesystem runs/ for legacy sync assessments
        d = RUNS_DIR / run_id
        if d.exists() and (d / "report.json").exists():
            rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
            return {"run_id": run_id, "status": "completed", "report": rep}
        raise HTTPException(404, "job not found")
    return {
        "run_id": row["run_id"],
        "thread_id": row.get("thread_id"),
        "status": row["status"],
        "vendor": row.get("vendor"),
        "overall": row.get("overall"),
        "cost_usd": row.get("cost_usd"),
        "duration_s": row.get("duration_s"),
        "stage_timings": row.get("stage_timings"),
        "report": row.get("report_json"),
        "trace": row.get("trace_json"),
        "approval": row.get("approval_json"),
        "updated_at": row.get("updated_at"),
    }


@app.post("/approve/{run_id}")
def approve(run_id: str, body: ApproveBody, identity: tuple[str, list[str]] = Depends(require_reviewer)):
    user_id, _groups = identity
    row = db.get_assessment(run_id)
    if row and row.get("status") == "awaiting_approval":
        try:
            approval = resume_assessment_job(
                run_id,
                decision=body.decision,
                approver=body.approver or user_id,
                comment=body.comment,
            )
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"resume failed: {exc}") from exc
        return approval

    # Legacy filesystem path (pre-queue sync runs)
    d = _run_dir(run_id)
    rep = json.loads((d / "report.json").read_text(encoding="utf-8"))
    if body.decision == "approve" and rep["overall"] == "BLOCKED":
        raise HTTPException(409, "A BLOCKED assessment cannot be approved. Resolve the blocking requirement or change the data tier.")
    rep["approval"].update({
        "status": "approved" if body.decision == "approve" else "rejected",
        "decided_by": body.approver or user_id,
        "decided_on": date.today().isoformat(),
        "comment": body.comment,
    })
    (d / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(d / "trace.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"stage": "approval", **rep["approval"]}) + "\n")
    db.upsert_assessment(
        run_id=run_id, thread_id=run_id, vendor=rep["request"]["vendor"], question=rep["request"]["question"],
        tier=rep["request"]["tier"], users=rep["request"]["users"], status="completed", overall=rep["overall"],
        report=rep, approval=rep["approval"], cost_usd=rep.get("cost_usd") or 0, duration_s=rep.get("duration_s") or 0,
    )
    return rep["approval"]


@app.get("/vendors/{name}/history")
def vendor_history(name: str, limit: int = 20):
    rows = db.list_vendor_history(name, limit=limit)
    history = []
    prev_overall = None
    for r in reversed(rows):  # oldest → newest for diff narrative
        item = {
            "run_id": r.get("run_id"),
            "overall": r.get("overall"),
            "status": r.get("status"),
            "cost_usd": r.get("cost_usd"),
            "duration_s": r.get("duration_s"),
            "created_at": r.get("created_at"),
            "approval": r.get("approval_json"),
            "changed_since_previous": prev_overall is not None and prev_overall != r.get("overall"),
            "previous_overall": prev_overall,
        }
        history.append(item)
        prev_overall = r.get("overall")
    history.reverse()
    return {"vendor": name, "n": len(history), "history": history}


@app.get("/observability")
def observability(limit: int = 20):
    return db.observability_summary(limit=limit)


@app.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def report_md(run_id: str):
    d = RUNS_DIR / run_id
    p = d / "report.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    row = db.get_assessment(run_id)
    if not row or not row.get("report_json"):
        raise HTTPException(404, "report not found")
    # Minimal markdown from stored JSON
    rep = row["report_json"]
    if isinstance(rep, str):
        rep = json.loads(rep)
    return f"# {rep.get('overall')}\n\n{rep.get('overall_reason', '')}\n"


def _run_dir(run_id: str) -> Path:
    p = RUNS_DIR / run_id
    if not p.exists() or ".." in run_id:
        raise HTTPException(404, "run not found")
    return p
