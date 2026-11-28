"""
RQ worker entrypoints for assessments (Production RAG Module 13 pattern).

  rq worker assess --url $REDIS_URL
  # or Windows SimpleWorker via: python -c "from app.worker import main; main()"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.graph import Pipeline, new_state  # noqa: E402
from assessor.tracing import Budget, Tracer  # noqa: E402

from app import db  # noqa: E402


def _serialize_state_snapshot(s: dict) -> dict:
    """JSON-safe preview for polling while awaiting approval."""
    out = {
        "route": s.get("route"),
        "vendor": s.get("vendor"),
        "overall": s.get("overall"),
        "overall_reason": s.get("overall_reason"),
        "open_questions": s.get("open_questions") or [],
        "stage_timings": s.get("stage_timings") or {},
    }
    if s.get("results"):
        out["results"] = [
            {
                "requirement_id": r.requirement_id,
                "title": r.title,
                "verdict": r.verdict,
                "reason": r.reason,
                "evidence_urls": r.evidence_urls,
                "clause": r.clause,
                "severity": r.severity,
            }
            for r in s["results"]
        ]
    if s.get("profile") is not None:
        out["profile"] = s["profile"].model_dump(mode="json")
    return out


def run_assessment_job(payload: dict) -> dict:
    """Execute assessment until human_gate interrupt (or completion for non-assessment routes)."""
    db.migrate()
    run_id = payload["run_id"]
    thread_id = payload.get("thread_id") or run_id
    tracer = Tracer("api", run_id=run_id)

    db.upsert_assessment(
        run_id=run_id, thread_id=thread_id, vendor=payload["vendor"], question=payload["question"],
        tier=payload.get("tier", "T3"), users=int(payload.get("users") or 1),
        status="running", requested_by=payload.get("requested_by") or "api",
        user_groups=payload.get("user_groups") or [],
    )

    pipe = Pipeline(tracer=tracer, budget=Budget())
    s = new_state(
        payload["question"],
        user_groups=payload.get("user_groups") or ["public"],
        tier=payload.get("tier", "T3"),
        users=int(payload.get("users") or 1),
        vendor=payload.get("vendor"),
        domain=payload.get("official_domain"),
        requested_by=payload.get("requested_by") or "api",
        await_human=True,
    )
    try:
        out = pipe.run(s, engine="langgraph", thread_id=thread_id)
    except Exception as exc:  # noqa: BLE001
        db.upsert_assessment(
            run_id=run_id, thread_id=thread_id, vendor=payload["vendor"], question=payload["question"],
            tier=payload.get("tier", "T3"), users=int(payload.get("users") or 1),
            status="failed", requested_by=payload.get("requested_by") or "api",
            user_groups=payload.get("user_groups") or [],
            report={"error": str(exc)},
        )
        tracer.close()
        raise

    interrupted = bool(out.get("__interrupt__"))
    timings = out.get("stage_timings") or {}
    cost = round(pipe.budget.spent_usd, 4)
    duration = round(pipe.budget.elapsed_s, 2)
    trace_events = list(tracer.events)

    if interrupted:
        preview = _serialize_state_snapshot(out)
        (tracer.dir / "pending.json").write_text(json.dumps(preview, indent=2, default=str), encoding="utf-8")
        db.upsert_assessment(
            run_id=run_id, thread_id=thread_id, vendor=payload["vendor"], question=payload["question"],
            tier=payload.get("tier", "T3"), users=int(payload.get("users") or 1),
            status="awaiting_approval", overall=out.get("overall"),
            report=preview, trace=trace_events, stage_timings=timings,
            cost_usd=cost, duration_s=duration,
            requested_by=payload.get("requested_by") or "api",
            user_groups=payload.get("user_groups") or [],
        )
        tracer.close()
        return {"run_id": run_id, "status": "awaiting_approval", "overall": out.get("overall")}

    rep = out.get("report")
    report_data = rep.model_dump(mode="json") if rep is not None else {"answer": out.get("answer"), "route": out.get("route")}
    db.upsert_assessment(
        run_id=run_id, thread_id=thread_id, vendor=payload["vendor"], question=payload["question"],
        tier=payload.get("tier", "T3"), users=int(payload.get("users") or 1),
        status="completed", overall=(rep.overall if rep else out.get("route")),
        report=report_data, trace=trace_events, stage_timings=timings,
        cost_usd=cost, duration_s=duration,
        requested_by=payload.get("requested_by") or "api",
        user_groups=payload.get("user_groups") or [],
        approval=(rep.approval.model_dump(mode="json") if rep else None),
    )
    tracer.close()
    return {"run_id": run_id, "status": "completed", "overall": report_data.get("overall")}


def resume_assessment_job(run_id: str, decision: str, approver: str, comment: str = "") -> dict:
    """Resume a paused LangGraph thread and finalize the report."""
    row = db.get_assessment(run_id)
    if not row:
        raise ValueError("run not found")
    if decision == "approve" and row.get("overall") == "BLOCKED":
        raise PermissionError("A BLOCKED assessment cannot be approved.")

    thread_id = row.get("thread_id") or run_id
    tracer = Tracer("api", run_id=run_id)
    pipe = Pipeline(tracer=tracer, budget=Budget())
    out = pipe.resume(thread_id, decision=decision, approver=approver, comment=comment)
    rep = out.get("report")
    if rep is None:
        # Fallback: if checkpoint was lost, rebuild approval onto pending snapshot.
        raise RuntimeError("Resume did not produce a report — checkpoint may be missing.")

    report_data = rep.model_dump(mode="json")
    db.upsert_assessment(
        run_id=run_id, thread_id=thread_id, vendor=row["vendor"], question=row["question"],
        tier=row["tier"], users=row["users"], status="completed", overall=rep.overall,
        report=report_data, trace=list(tracer.events),
        stage_timings=out.get("stage_timings") or row.get("stage_timings") or {},
        cost_usd=rep.cost_usd, duration_s=rep.duration_s,
        requested_by=row.get("requested_by") or "api",
        user_groups=row.get("user_groups") or [],
        approval=rep.approval.model_dump(mode="json"),
    )
    tracer.close()
    return report_data["approval"]


def main() -> None:
    """Run an RQ worker for the assess queue (SimpleWorker works on Windows)."""
    from rq import Worker

    from app import settings
    from app.settings import normalize_redis_url
    from redis import Redis

    url = normalize_redis_url(settings.REDIS_URL)
    kwargs = {}
    if url.startswith("rediss://"):
        kwargs["ssl_cert_reqs"] = None
    redis = Redis.from_url(url, **kwargs)
    # RQ 2+/3+: pass connection= explicitly (Connection context manager removed).
    try:
        from rq import SimpleWorker

        worker = SimpleWorker([settings.QUEUE_NAME], connection=redis)
    except Exception:
        worker = Worker([settings.QUEUE_NAME], connection=redis)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
