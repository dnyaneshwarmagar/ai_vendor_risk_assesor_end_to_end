"""
router.py — decide which line a question takes: policy library, vendor research, full assessment, or refuse.

COURSE MAP
  Agentic RAG guide  "agents.py → The Router" and "tasks.py → Task 1: route". Same idea, more routes:
  the course routes between "our PDF" and "the web"; here we route between "our policies", "the vendor's
  web presence", "both, then match" (assessment), or refuse.

Offline / mock: deterministic regex router for CI and gold-set runs.
Live LLM: `LLM.structured()` → RouteDecision (validate → repair). Ported goal/backstory from the kit.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Optional

from .llm import LLM
from .schemas import RouteDecision

# Ported from Agentic RAG Study Kit agents.create_router_agent (goal + backstory),
# retargeted to Nimbu Mart's four routes. The "semantic MEANING" sentence is load-bearing —
# see docs/m3-router-graders.md ("Break the Router on purpose").
ROUTER_SYSTEM = """You are the Router for Nimbu Mart's vendor-risk assistant.

Goal: send each user question to the right pipeline based on what the question is really about.

Backstory: You are an expert at deciding whether a question can be answered from Nimbu Mart's
internal policy library (vectorstore of security, privacy, AI-use, procurement and Approved Vendor
List documents), needs only public facts about a named vendor/tool from the web, needs both
(an assessment that matches policy requirements to vendor facts), or must be refused.
You make routing decisions based on the semantic MEANING of the question, not just on matching keywords.

Routes (exactly one):
- "policy": asks what OUR internal policy / AVL / process says (clauses, tiers, who approves, residency
  rules, what is required). May name a vendor when asking what *our records* say about them
  (e.g. "Which tier is Parakeet approved for?"). Needs no fresh vendor-web research.
- "vendor": asks a factual question about a specific vendor/tool (certifications, regions, incidents,
  DPA, SSO) with no ask to use/adopt/assess against policy.
- "assessment": asks whether a team CAN/MAY/SHOULD use a tool, or to assess/review/check/onboard a
  vendor against policy. Includes questions that mix a vendor fact with a use decision
  (e.g. "Is LedgerLens SOC 2 so we can use it?"). Needs policy + vendor facts.
- "refuse": not about vendors/tools/policy, or asks YOU to approve / sign off (only humans approve — AI-5.1).

Return JSON: {"route": "policy"|"vendor"|"assessment"|"refuse", "vendor": "<name or null>", "reason": "..."}
If a known vendor is clearly named, set vendor to that exact name; otherwise null."""

ASSESS_RE = re.compile(
    r"\b(can|may|should|could|allowed|ok(ay)? to|safe to|assess|review|evaluate|check|onboard|approve)\b"
    r".*\b(use|using|adopt|buy|onboard|vendor|tool)\b"
    r"|\b(assess|review|evaluate|check)\b"
    r"|\bso we can use\b|\bfor (us|our team) to use\b",
    re.I,
)
POLICY_RE = re.compile(
    r"\b(policy|policies|clause|tier|t[123]\b|who approves|required|requirement|must|dpdp|"
    r"our (rules|process)|approved for)\b",
    re.I,
)


def guess_vendor(question: str, known_vendors: Iterable[str]) -> Optional[str]:
    q = question.lower()
    # Longer names first so "LedgerLens AI" wins over a bare substring clash.
    for v in sorted(known_vendors, key=len, reverse=True):
        if v.lower() in q:
            return v
    return None


def _mock_decide(question: str, vendor: Optional[str]) -> dict:
    # Human-approval asks and clear off-topic → refuse (AI-5.1 / out of scope).
    if re.search(r"\b(please )?approve\b|\bmark\b.*\bapproved\b|\bsign off\b", question, re.I):
        return {"route": "refuse", "vendor": vendor, "reason": "Only a human approver can approve a vendor (AI-5.1)."}
    if re.search(r"\b(weather|poem|joke|sourdough|recipe|skip the (policy|security )?checks)\b", question, re.I):
        return {"route": "refuse", "vendor": vendor, "reason": "Out of scope for the vendor-risk assistant."}
    if vendor and ASSESS_RE.search(question):
        return {"route": "assessment", "vendor": vendor, "reason": "Asks whether a named tool may be used → needs policy + vendor facts."}
    if vendor and POLICY_RE.search(question):
        return {"route": "policy", "vendor": vendor, "reason": "Asks what OUR records/policy say about a named vendor → policy library."}
    if vendor:
        return {"route": "vendor", "vendor": vendor, "reason": "Factual question about a named vendor."}
    return {"route": "policy", "vendor": None, "reason": "No vendor named → internal policy question."}


def decide(
    question: str,
    known_vendors: Iterable[str],
    llm: Optional[LLM] = None,
    *,
    force_llm: bool = False,
) -> RouteDecision:
    """Route a question. Offline/mock stays regex-deterministic unless force_llm=True (M3 eval)."""
    known = list(known_vendors)
    vendor = guess_vendor(question, known)

    def mock() -> dict:
        return _mock_decide(question, vendor)

    llm = llm or LLM()
    from .config import SETTINGS

    # Offline gold / CI: regex mock. Live search or VRA_FORCE_LLM_ROUTER=1 / force_llm: LLM agent.
    force = force_llm or os.environ.get("VRA_FORCE_LLM_ROUTER", "").strip() == "1"
    if llm.mock_mode or (SETTINGS.search_provider == "offline" and not force):
        return RouteDecision.model_validate(mock())

    user = (
        f"Known vendors (prefer exact names when present): {', '.join(known) or 'none'}\n"
        f"Question: {question}"
    )
    decision = llm.structured(ROUTER_SYSTEM, user, RouteDecision, stage="route", mock=mock)
    # Keep identity anchors from the user/known list when the model invents a name.
    if decision.vendor and known:
        matched = guess_vendor(decision.vendor, known) or guess_vendor(question, known)
        if matched:
            decision.vendor = matched
    elif vendor and not decision.vendor:
        decision.vendor = vendor
    return decision
