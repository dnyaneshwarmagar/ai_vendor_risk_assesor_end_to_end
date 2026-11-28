"""Cloud DATABASE_URL / REDIS_URL normalization (Neon + Upstash)."""

from app.settings import normalize_database_url, normalize_redis_url


def test_neon_gets_sslmode_require():
    url = normalize_database_url("postgresql://u:p@ep-cool.neon.tech/neondb")
    assert "sslmode=require" in url
    assert url.startswith("postgresql://")


def test_postgres_scheme_normalized():
    url = normalize_database_url("postgres://u:p@ep-cool.neon.tech/neondb")
    assert url.startswith("postgresql://")
    assert "sslmode=require" in url


def test_localhost_postgres_no_forced_ssl():
    url = normalize_database_url("postgresql://vra:vra@localhost:5433/vendor_risk")
    assert "sslmode" not in url


def test_existing_sslmode_preserved():
    url = normalize_database_url("postgresql://u:p@ep-cool.neon.tech/neondb?sslmode=verify-full")
    assert "sslmode=verify-full" in url
    assert url.count("sslmode") == 1


def test_upstash_redis_upgraded_to_rediss():
    url = normalize_redis_url("redis://default:token@aware-cow-12345.upstash.io:6379")
    assert url.startswith("rediss://")


def test_local_redis_unchanged():
    assert normalize_redis_url("redis://localhost:6379/0") == "redis://localhost:6379/0"
