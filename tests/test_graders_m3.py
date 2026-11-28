"""Milestone 3: graders catch hallucinations; mock router still covers awkward assessment phrasing."""
from assessor.graders import grade_grounded, grade_policy_answer, grade_relevance
from assessor.llm import LLM
from assessor.router import decide
from assessor.schemas import PolicyAnswer, PolicyHit


def test_awkward_assessment_routes_as_assessment():
    d = decide("Is LedgerLens AI SOC 2 so we can use it?", ["LedgerLens AI", "QuillDesk", "Parakeet Translate"])
    assert d.route == "assessment", d.reason


def test_parakeet_tier_is_policy_not_vendor():
    d = decide("Which tier is Parakeet Translate approved for?", ["LedgerLens AI", "QuillDesk", "Parakeet Translate"])
    assert d.route == "policy", d.reason


def test_hallucinated_clause_is_not_grounded():
    sources = (
        "AI-5.1 Human approval required. The assistant never approves vendors. "
        "Approvers for T3: Head of Information Security and DPO."
    )
    invented = (
        "Per FAKE-9.9, all vendors are automatically approved for T3 use without human review "
        "and customer data may leave India freely."
    )
    g = grade_grounded(invented, sources, LLM())
    assert g.verdict is False, g.reason


def test_grade_policy_answer_abstains_on_invention():
    hit = PolicyHit(
        doc="ai_acceptable_use_policy.md",
        title="AI Acceptable Use Policy",
        doc_id="NM-AI-AUP",
        clause_id="AI-5.1",
        heading="Human approval",
        text="AI-5.1 Human approval required. The assistant never approves vendors.",
        score=0.9,
        version="2026.1",
    )
    pa = PolicyAnswer(
        question="Who approves a T3 tool?",
        answer="Per FAKE-9.9 every tool is auto-approved by the assistant for immediate T3 production use.",
        citations=[hit],
        mode="llm",
    )
    graded = grade_policy_answer(pa, LLM())
    assert graded.abstained is True
    assert graded.grader_grounded is False


def test_relevant_context_passes_heuristic():
    ctx = "DP-3.1 Customer personal data must be stored in India at rest."
    r = grade_relevance("Where must customer personal data be stored?", ctx, LLM())
    assert r.verdict is True
