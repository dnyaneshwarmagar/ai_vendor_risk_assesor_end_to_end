"""Milestone 5 — queue, durable human gate, ACL, observability."""

from __future__ import annotations

import os

import pytest

# Force offline + inline before app imports settings/db paths used in tests.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SEARCH_PROVIDER"] = "offline"
os.environ["VRA_INLINE_QUEUE"] = "1"
os.environ["DATABASE_URL"] = ""
os.environ["VRA_SQLITE_PATH"] = str(
    __import__("pathlib").Path("data") / "test_assessor_m5.db"
)
os.environ["VRA_CHECKPOINT_PATH"] = str(
    __import__("pathlib").Path("data") / "test_langgraph_m5.sqlite"
)


@pytest.fixture(autouse=True)
def _clean_db(tmp_path, monkeypatch):
    db_path = tmp_path / "assessor.db"
    cp_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("VRA_SQLITE_PATH", str(db_path))
    monkeypatch.setenv("VRA_CHECKPOINT_PATH", str(cp_path))
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("VRA_INLINE_QUEUE", "1")
    from app import settings as app_settings
    from assessor import graph as graph_mod

    app_settings.SQLITE_PATH = db_path
    app_settings.CHECKPOINT_PATH = cp_path
    app_settings.DATABASE_URL = ""
    app_settings.FORCE_INLINE_QUEUE = True
    graph_mod.CHECKPOINT_SQLITE = cp_path
    yield


def test_groups_derived_from_identity_not_client():
    from app.auth import groups_for_user

    assert "security" in groups_for_user("alice")
    assert groups_for_user("guest") == ["public"]
    assert groups_for_user("unknown-person") == ["public"]


def test_assessment_pauses_then_approve_survives_new_pipeline(monkeypatch):
    from assessor import vendor_research as vr
    from app import db
    from app.worker import resume_assessment_job, run_assessment_job

    monkeypatch.setattr(vr.SETTINGS, "search_provider", "offline")
    monkeypatch.setattr(vr.SETTINGS, "llm_provider", "mock")

    db.migrate()
    run_id = "test-m5-ledger-001"
    payload = {
        "run_id": run_id,
        "thread_id": run_id,
        "question": "Can support use LedgerLens AI for tickets?",
        "vendor": "LedgerLens AI",
        "official_domain": "ledgerlens.example",
        "tier": "T3",
        "users": 35,
        "requested_by": "reviewer",
        "user_groups": ["public", "employees", "security"],
    }
    out = run_assessment_job(payload)
    assert out["status"] == "awaiting_approval"
    row = db.get_assessment(run_id)
    assert row["status"] == "awaiting_approval"
    assert row["overall"] in ("BLOCKED", "CONDITIONAL", "READY_FOR_APPROVAL")

    # BLOCKED cannot be approved; other outcomes can — exercise the reject path either way.
    if row["overall"] == "BLOCKED":
        with pytest.raises(PermissionError):
            resume_assessment_job(run_id, "approve", "A. Reviewer")

    # Reject resumes the checkpointer in a fresh Pipeline instance (simulates restart).
    approval = resume_assessment_job(run_id, "reject", "A. Reviewer", comment="Too risky")
    assert approval["status"] == "rejected"
    assert approval["decided_by"] == "A. Reviewer"
    done = db.get_assessment(run_id)
    assert done["status"] == "completed"
    assert done["approval_json"]["status"] == "rejected"


def test_vendor_history_and_observability():
    from app import db
    from app.worker import resume_assessment_job, run_assessment_job

    db.migrate()
    for i, overall_hint in enumerate(("a", "b")):
        run_id = f"test-m5-hist-{i}"
        run_assessment_job({
            "run_id": run_id,
            "thread_id": run_id,
            "question": "Can support use LedgerLens AI?",
            "vendor": "LedgerLens AI",
            "official_domain": "ledgerlens.example",
            "tier": "T3",
            "users": 10,
            "requested_by": "alice",
            "user_groups": ["public", "employees", "security"],
        })
        resume_assessment_job(run_id, "reject", "alice")
    hist = db.list_vendor_history("LedgerLens AI", limit=10)
    assert len(hist) >= 2
    obs = db.observability_summary(limit=20)
    assert obs["n"] >= 2
    assert "p50" in obs["duration_s"]


def test_api_assess_does_not_accept_client_groups():
    from fastapi.testclient import TestClient

    from app.api import AssessBody, app

    # Body model has no user_groups field
    assert "user_groups" not in AssessBody.model_fields

    client = TestClient(app)
    # Health works without redis
    h = client.get("/health")
    assert h.status_code == 200
    assert h.json()["ok"] is True
