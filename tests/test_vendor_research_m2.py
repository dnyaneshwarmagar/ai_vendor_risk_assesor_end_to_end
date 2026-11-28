"""Milestone 2 helpers: planner, reviewer, stop rules, identity gate (mocked, no network)."""
from datetime import date

from assessor.schemas import EntityAnchor, ResearchPlan, SubQuestion, VendorFact, VendorProfile
from assessor.tracing import Budget
from assessor.vendor_research import (
    VendorResearcher,
    _mock_plan,
    evaluate_progress,
    review_plan,
)


def test_mock_plan_one_subquestion_per_field():
    plan = _mock_plan("Notion", "notion.so")
    fields = {f for q in plan.sub_questions for f in q.fields}
    assert "legal_entity" in fields
    assert "security_certifications" in fields
    assert any(q.lens == "entity" for q in plan.sub_questions)
    assert any(q.high_stakes for q in plan.sub_questions)


def test_review_plan_adds_entity_and_stop_criteria():
    bare = ResearchPlan(
        goal="test",
        entity=EntityAnchor(name="Acme", official_domain="acme.com"),
        sub_questions=[SubQuestion(id="q1", question="certs?", fields=["security_certifications"])],
        stop_criteria=[],
    )
    plan, review = review_plan(bare)
    assert any(q.lens == "entity" for q in plan.sub_questions)
    assert any(q.high_stakes for q in plan.sub_questions if "security_certifications" in q.fields)
    stop = " ".join(plan.stop_criteria).lower()
    assert "documented" in stop and "two search" in stop
    assert review.fixes_applied


def test_evaluate_progress_stops_when_high_stakes_documented():
    plan = _mock_plan("Notion", "notion.so")
    profile = VendorProfile(vendor="Notion", official_domain="notion.so", as_of=date(2026, 11, 1))
    for f in ("security_certifications", "security_incidents", "trains_on_customer_data", "data_regions"):
        profile.facts[f] = VendorFact(
            field=f, value={}, display="ok", confidence=0.9, evidence_level="documented", sources=["https://trust.notion.com/"]
        )
    decision = evaluate_progress(plan, profile, iteration=1, max_iterations=2, new_evidence=3,
                                 budget=Budget(max_usd=0.5), search_failures={})
    assert decision.action == "stop"
    assert "documented" in " ".join(decision.reasons).lower() or "failed" in " ".join(decision.reasons).lower()


def test_evaluate_progress_stops_after_two_search_failures():
    plan = _mock_plan("Notion", "notion.so")
    profile = VendorProfile(vendor="Notion", official_domain="notion.so", as_of=date(2026, 11, 1))
    failures = {f: 2 for f in (
        "security_certifications", "security_incidents", "trains_on_customer_data", "data_regions",
        "legal_entity", "subprocessors", "data_retention", "sso_saml", "dpa_available",
    )}
    decision = evaluate_progress(plan, profile, iteration=1, max_iterations=2, new_evidence=0,
                                 budget=Budget(max_usd=0.5), search_failures=failures)
    assert decision.action == "stop"


def test_identity_gate_rejects_non_matching_host_in_mock_live(monkeypatch):
    from assessor import vendor_research as vr
    monkeypatch.setattr(vr.SETTINGS, "search_provider", "ddgs")
    r = VendorResearcher()
    r.offline_search = False
    ok, reason = r.identity_gate(
        {"url": "https://other-company.example/about", "title": "Other", "text": "We are Other Co."},
        "Notion",
        "notion.so",
        product="Notion",
    )
    assert ok is False
    assert "reject" in reason.lower() or "match" in reason.lower()


def test_identity_gate_accepts_official_domain_in_mock_live(monkeypatch):
    from assessor import vendor_research as vr
    monkeypatch.setattr(vr.SETTINGS, "search_provider", "ddgs")
    r = VendorResearcher()
    r.offline_search = False
    ok, _ = r.identity_gate(
        {"url": "https://www.notion.so/security", "title": "Security", "text": "Notion SOC 2"},
        "Notion",
        "notion.so",
        product="Notion",
    )
    assert ok is True


def test_offline_research_unchanged_lookalike(monkeypatch):
    """Regression: offline suite behaviour must not break under M2 changes."""
    from assessor import vendor_research as vr
    monkeypatch.setattr(vr.SETTINGS, "search_provider", "offline")
    monkeypatch.setattr(vr.SETTINGS, "llm_provider", "mock")
    profile = VendorResearcher().research("LedgerLens AI")
    assert "https://ledgerlens-uk.example/about-us" in profile.rejected
    assert "security_certifications" in profile.facts
