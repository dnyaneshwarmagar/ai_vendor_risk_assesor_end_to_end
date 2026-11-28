"""
Assessment store — Postgres when DATABASE_URL is set, else SQLite.

Stores reports + stage timings so /vendors/{name}/history and the last-20 observability
table survive a server restart (SEC-12.1 / Production RAG Lab 13).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional
from urllib.parse import urlparse

from . import settings

_lock = threading.Lock()

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS assessments (
    run_id          TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    vendor          TEXT NOT NULL,
    question        TEXT NOT NULL,
    tier            TEXT NOT NULL,
    users           INTEGER NOT NULL,
    overall         TEXT,
    status          TEXT NOT NULL DEFAULT 'queued',
    report_json     TEXT,
    trace_json      TEXT,
    stage_timings   TEXT,
    cost_usd        REAL DEFAULT 0,
    duration_s      REAL DEFAULT 0,
    requested_by    TEXT,
    user_groups     TEXT,
    approval_json   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assessments_vendor ON assessments (vendor, created_at);
CREATE INDEX IF NOT EXISTS assessments_created ON assessments (created_at);
"""

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS assessments (
    run_id          text PRIMARY KEY,
    thread_id       text NOT NULL,
    vendor          text NOT NULL,
    question        text NOT NULL,
    tier            text NOT NULL,
    users           integer NOT NULL,
    overall         text,
    status          text NOT NULL DEFAULT 'queued',
    report_json     jsonb,
    trace_json      jsonb,
    stage_timings   jsonb,
    cost_usd        double precision DEFAULT 0,
    duration_s      double precision DEFAULT 0,
    requested_by    text,
    user_groups     text[],
    approval_json   jsonb,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS assessments_vendor ON assessments (vendor, created_at DESC);
"""


def _use_postgres() -> bool:
    url = settings.DATABASE_URL or ""
    return bool(url) and url.startswith(("postgres://", "postgresql://"))


def _pg_url() -> str:
    from .settings import normalize_database_url

    return normalize_database_url(settings.DATABASE_URL)


@contextmanager
def connect() -> Iterator[Any]:
    if _use_postgres():
        import psycopg
        from psycopg.rows import dict_row

        # Neon / Supabase: sslmode=require is injected by normalize_database_url when missing.
        conn = psycopg.connect(_pg_url(), row_factory=dict_row, connect_timeout=30)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        settings.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(settings.SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def migrate() -> str:
    with _lock:
        with connect() as conn:
            if _use_postgres():
                conn.execute(SCHEMA_PG)
                return "postgres"
            conn.executescript(SCHEMA_SQLITE)
            return f"sqlite:{settings.SQLITE_PATH}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_assessment(
    *,
    run_id: str,
    thread_id: str,
    vendor: str,
    question: str,
    tier: str,
    users: int,
    status: str,
    requested_by: str = "",
    user_groups: list[str] | None = None,
    overall: str | None = None,
    report: dict | None = None,
    trace: list | None = None,
    stage_timings: dict | None = None,
    cost_usd: float = 0.0,
    duration_s: float = 0.0,
    approval: dict | None = None,
) -> None:
    migrate()
    now = _now()
    groups = user_groups or []
    with _lock:
        with connect() as conn:
            if _use_postgres():
                conn.execute(
                    """
                    INSERT INTO assessments (
                        run_id, thread_id, vendor, question, tier, users, overall, status,
                        report_json, trace_json, stage_timings, cost_usd, duration_s,
                        requested_by, user_groups, approval_json, created_at, updated_at
                    ) VALUES (
                        %(run_id)s, %(thread_id)s, %(vendor)s, %(question)s, %(tier)s, %(users)s,
                        %(overall)s, %(status)s, %(report)s::jsonb, %(trace)s::jsonb, %(timings)s::jsonb,
                        %(cost)s, %(dur)s, %(by)s, %(groups)s, %(approval)s::jsonb, %(now)s, %(now)s
                    )
                    ON CONFLICT (run_id) DO UPDATE SET
                        overall = EXCLUDED.overall,
                        status = EXCLUDED.status,
                        report_json = EXCLUDED.report_json,
                        trace_json = EXCLUDED.trace_json,
                        stage_timings = EXCLUDED.stage_timings,
                        cost_usd = EXCLUDED.cost_usd,
                        duration_s = EXCLUDED.duration_s,
                        approval_json = EXCLUDED.approval_json,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "run_id": run_id, "thread_id": thread_id, "vendor": vendor, "question": question,
                        "tier": tier, "users": users, "overall": overall, "status": status,
                        "report": json.dumps(report) if report is not None else None,
                        "trace": json.dumps(trace) if trace is not None else None,
                        "timings": json.dumps(stage_timings) if stage_timings is not None else None,
                        "cost": cost_usd, "dur": duration_s, "by": requested_by, "groups": groups,
                        "approval": json.dumps(approval) if approval is not None else None, "now": now,
                    },
                )
            else:
                conn.execute(
                    """
                    INSERT INTO assessments (
                        run_id, thread_id, vendor, question, tier, users, overall, status,
                        report_json, trace_json, stage_timings, cost_usd, duration_s,
                        requested_by, user_groups, approval_json, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET
                        overall=excluded.overall, status=excluded.status,
                        report_json=excluded.report_json, trace_json=excluded.trace_json,
                        stage_timings=excluded.stage_timings, cost_usd=excluded.cost_usd,
                        duration_s=excluded.duration_s, approval_json=excluded.approval_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        run_id, thread_id, vendor, question, tier, users, overall, status,
                        json.dumps(report) if report is not None else None,
                        json.dumps(trace) if trace is not None else None,
                        json.dumps(stage_timings) if stage_timings is not None else None,
                        cost_usd, duration_s, requested_by, json.dumps(groups),
                        json.dumps(approval) if approval is not None else None, now, now,
                    ),
                )


def get_assessment(run_id: str) -> Optional[dict]:
    migrate()
    with connect() as conn:
        if _use_postgres():
            row = conn.execute("SELECT * FROM assessments WHERE run_id = %s", (run_id,)).fetchone()
            return dict(row) if row else None
        row = conn.execute("SELECT * FROM assessments WHERE run_id = ?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None


def list_vendor_history(vendor: str, limit: int = 20) -> list[dict]:
    migrate()
    with connect() as conn:
        if _use_postgres():
            rows = conn.execute(
                "SELECT run_id, vendor, overall, status, cost_usd, duration_s, created_at, updated_at, "
                "report_json, approval_json FROM assessments WHERE lower(vendor)=lower(%s) "
                "ORDER BY created_at DESC LIMIT %s",
                (vendor, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        rows = conn.execute(
            "SELECT run_id, vendor, overall, status, cost_usd, duration_s, created_at, updated_at, "
            "report_json, approval_json FROM assessments WHERE lower(vendor)=lower(?) "
            "ORDER BY created_at DESC LIMIT ?",
            (vendor, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def list_recent(limit: int = 20) -> list[dict]:
    migrate()
    with connect() as conn:
        if _use_postgres():
            rows = conn.execute(
                "SELECT run_id, vendor, overall, status, cost_usd, duration_s, stage_timings, created_at "
                "FROM assessments ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        rows = conn.execute(
            "SELECT run_id, vendor, overall, status, cost_usd, duration_s, stage_timings, created_at "
            "FROM assessments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("report_json", "trace_json", "stage_timings", "approval_json", "user_groups"):
        if key in d and isinstance(d[key], str) and d[key]:
            try:
                d[key] = json.loads(d[key])
            except json.JSONDecodeError:
                pass
    return d


def observability_summary(limit: int = 20) -> dict:
    """Last N runs with p50/p95 latency and cost (Lab 13 style)."""
    rows = list_recent(limit)
    durs = sorted(float(r.get("duration_s") or 0) for r in rows)
    costs = sorted(float(r.get("cost_usd") or 0) for r in rows)

    def pct(vals: list[float], p: float) -> float:
        if not vals:
            return 0.0
        idx = min(len(vals) - 1, max(0, int(round((p / 100) * (len(vals) - 1)))))
        return round(vals[idx], 3)

    stage_samples: dict[str, list[float]] = {}
    for r in rows:
        timings = r.get("stage_timings") or {}
        if isinstance(timings, str):
            try:
                timings = json.loads(timings)
            except json.JSONDecodeError:
                timings = {}
        for stage, ms in (timings or {}).items():
            stage_samples.setdefault(stage, []).append(float(ms))

    stages = {
        s: {"p50_ms": pct(sorted(v), 50), "p95_ms": pct(sorted(v), 95), "n": len(v)}
        for s, v in stage_samples.items()
    }
    return {
        "n": len(rows),
        "duration_s": {"p50": pct(durs, 50), "p95": pct(durs, 95)},
        "cost_usd": {"p50": pct(costs, 50), "p95": pct(costs, 95)},
        "stages": stages,
        "runs": [
            {
                "run_id": r.get("run_id"),
                "vendor": r.get("vendor"),
                "overall": r.get("overall"),
                "status": r.get("status"),
                "duration_s": r.get("duration_s"),
                "cost_usd": r.get("cost_usd"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }


def backend_name() -> str:
    if _use_postgres():
        host = urlparse(settings.DATABASE_URL).hostname or "postgres"
        return f"postgres://{host}"
    return f"sqlite://{settings.SQLITE_PATH}"
