"""
Smoke-test cloud Postgres + Redis from .env (Neon / Upstash).

  python scripts/m5_cloud_smoke.py

Expects DATABASE_URL and REDIS_URL in .env. Does not print secrets.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db, settings  # noqa: E402
from app.settings import normalize_database_url, normalize_redis_url  # noqa: E402


def main() -> int:
    pg = normalize_database_url(settings.DATABASE_URL)
    rd = normalize_redis_url(settings.REDIS_URL)
    print("store target:", db.backend_name())
    print("redis scheme:", rd.split(":", 1)[0] if rd else "(empty)")
    print("inline queue:", settings.FORCE_INLINE_QUEUE)

    if not pg:
        print("FAIL: DATABASE_URL not set — add a Neon connection string to .env")
        return 1

    try:
        backend = db.migrate()
        print("migrate:", backend)
        with db.connect() as conn:
            if db._use_postgres():
                row = conn.execute("SELECT 1 AS ok").fetchone()
            else:
                row = conn.execute("SELECT 1 AS ok").fetchone()
        print("postgres ping: ok" if row else "postgres ping: empty")
    except Exception as exc:  # noqa: BLE001
        print("FAIL postgres:", type(exc).__name__, str(exc)[:200])
        return 1

    try:
        from redis import Redis

        kwargs = {}
        if rd.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = None
        Redis.from_url(rd, **kwargs).ping()
        print("redis ping: ok")
    except Exception as exc:  # noqa: BLE001
        print("FAIL redis:", type(exc).__name__, str(exc)[:200])
        return 1

    if settings.FORCE_INLINE_QUEUE:
        print("NOTE: VRA_INLINE_QUEUE=1 — set to 0 to use cloud Redis with RQ workers")

    print("PASS: cloud Postgres + Redis reachable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
