"""Milestone 6 — gold size, reason-judge calibration, ablation knobs."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SEARCH_PROVIDER", "offline")


def test_real_gold_is_ten_by_eight():
    gold = json.loads((ROOT / "data" / "gold_set_real.json").read_text(encoding="utf-8"))
    assert len(gold["cases"]) == 10
    fields = {
        "security_certifications",
        "data_regions",
        "trains_on_customer_data",
        "subprocessors",
        "data_retention",
        "sso_saml",
        "security_incidents",
        "dpa_available",
    }
    kinds = {c.get("case_kind") for c in gold["cases"]}
    assert {"clear_pass", "clear_fail", "messy"} <= kinds
    for case in gold["cases"]:
        assert set(case["expected_facts"]) == fields
        assert case.get("sources"), case["id"]
        assert all(s.get("url") and s.get("checked_on") for s in case["sources"])


def test_reason_judge_calibration_meets_threshold():
    from eval.reason_judge import calibrate

    assert calibrate(strict=True, force_heuristic=True) == 0


def test_ablation_env_knobs(monkeypatch):
    from assessor import vendor_research as vr
    from assessor.config import Settings
    from datetime import date

    monkeypatch.setenv("VRA_FRESHNESS_DECAY", "0")
    monkeypatch.setenv("VRA_RERANKER", "0")
    monkeypatch.setenv("VRA_IDENTITY_GATE", "0")
    s = Settings()
    assert s.freshness_decay is False
    assert s.use_reranker is False
    assert s.identity_gate is False

    vr.SETTINGS.freshness_decay = False
    assert vr.freshness("security_certifications", None, date(2026, 11, 1)) == 1.0
    vr.SETTINGS.freshness_decay = True
