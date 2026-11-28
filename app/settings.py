"""Product settings for API / worker / UI (Milestone 5)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def normalize_database_url(url: str) -> str:
    """Ensure cloud Postgres URLs use TLS (Neon/Supabase need sslmode=require)."""
    url = (url or "").strip()
    if not url:
        return url
    # Heroku-style scheme → psycopg
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
    q = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if not local and "sslmode" not in {k.lower() for k in q}:
        q["sslmode"] = "require"
    return urlunparse(parsed._replace(query=urlencode(q)))


def normalize_redis_url(url: str) -> str:
    """Prefer rediss:// for cloud Redis (Upstash). Leave local redis:// alone."""
    url = (url or "").strip() or "redis://localhost:6379/0"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    local = host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")
    if local:
        return url
    # Upstash / managed Redis expect TLS
    if parsed.scheme == "redis" and (
        "upstash" in host or "redis.cloud" in host or "redislabs" in host or "cache.amazonaws" in host
    ):
        return urlunparse(parsed._replace(scheme="rediss"))
    return url


# Postgres when set; otherwise SQLite file (survives restart, no Docker required for demos).
DATABASE_URL = normalize_database_url(_env("DATABASE_URL", ""))
SQLITE_PATH = Path(_env("VRA_SQLITE_PATH", str(ROOT / "data" / "assessor.db")))

REDIS_URL = normalize_redis_url(_env("REDIS_URL", "redis://localhost:6379/0"))
QUEUE_NAME = _env("QUEUE_NAME", "assess")
# 1 = always run jobs in-process (tests / no Redis). 0 = try Redis+RQ, fall back to thread.
FORCE_INLINE_QUEUE = _env("VRA_INLINE_QUEUE", "0") == "1"

API_BASE = _env("VRA_API_BASE", "http://127.0.0.1:8000")
CHECKPOINT_PATH = Path(_env("VRA_CHECKPOINT_PATH", str(ROOT / "data" / "langgraph_checkpoints.sqlite")))

# Demo identity directory: X-User-Id → groups. Never trust client-supplied groups.
IDENTITY_MAP = {
    "alice": ["public", "employees", "security"],
    "bob": ["public", "employees", "procurement"],
    "carol": ["public", "employees", "security", "procurement"],
    "reviewer": ["public", "employees", "security", "procurement"],
    "guest": ["public"],
}
