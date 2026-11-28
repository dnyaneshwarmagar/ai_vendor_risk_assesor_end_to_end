"""
graders.py — the two checks before an answer leaves the system.

COURSE MAP
  Agentic RAG guide  "agents.py → Answer Grader" (is the retrieved text relevant to the question?) and
                     "Hallucination Grader" (is every statement in the answer supported by the sources?).
  Production RAG     Module 9 "Reasoning, self-checks and guardrails"; Module 10 faithfulness.

Offline: heuristics so the pipeline runs end to end.
Live: LLM.structured() with GradeResult; callers (policy_rag) own the retry loop.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from .llm import LLM
from .policy_rag import tokenize
from .schemas import PolicyAnswer


class GradeResult(BaseModel):
    verdict: bool
    reason: str = ""


# Ported from Agentic RAG Study Kit create_answer_grader_agent / create_hallucination_grader_agent.
RELEVANCE_SYSTEM = """You are the Answer Grader for Nimbu Mart's policy assistant.

Goal: filter out wrong or irrelevant retrievals.

Backstory: You are a strict grader. You read the question and the retrieved policy text and judge
only one thing: does this text actually address the question? Related topic is not enough — the
key ideas needed to answer must be present. If the context cannot support an answer, verdict is false.

Return JSON: {"verdict": true|false, "reason": "..."}."""

GROUNDED_SYSTEM = """You are the Hallucination Grader for Nimbu Mart's policy assistant.

Goal: catch made-up facts before they reach the user.

Backstory: You are a fact checker. You compare the draft answer with the source text and decide
whether every important claim is supported by that source. An answer that invents facts, clause
ids, numbers, names or approvals that are not in the sources is a hallucination — verdict false.

Return JSON: {"verdict": true|false, "reason": "..."}."""


def grade_relevance(question: str, context: str, llm: Optional[LLM] = None) -> GradeResult:
    def mock() -> dict:
        q, c = set(tokenize(question)), set(tokenize(context))
        overlap = len(q & c)
        return {"verdict": overlap >= max(1, len(q) // 3), "reason": f"{overlap}/{len(q)} question terms found in context (heuristic)"}

    client = llm or LLM()
    try:
        return client.structured(RELEVANCE_SYSTEM, f"Question: {question}\n\nContext:\n{context[:6000]}",
                                 GradeResult, stage="grade_relevance", mock=mock)
    except Exception:  # noqa: BLE001 — live grader loops must not crash the assessor
        return GradeResult.model_validate(mock())


def grade_grounded(answer: str, sources: str, llm: Optional[LLM] = None) -> GradeResult:
    def mock() -> dict:
        src = set(tokenize(sources))
        body = re.sub(r"^[A-Z]{1,5}-[\d.]+:\s*", "", answer)
        body = re.sub(r"\(source:.*?\)\s*$", "", body).strip()
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\s*\|\s*", body) if len(tokenize(s)) >= 3]
        unsupported = [s for s in sentences if len(set(tokenize(s)) & src) / max(1, len(set(tokenize(s)))) < 0.6]
        return {"verdict": not unsupported, "reason": ("all sentences supported" if not unsupported else f"unsupported: {unsupported[0][:80]}") + " (heuristic)"}

    client = llm or LLM()
    try:
        return client.structured(GROUNDED_SYSTEM, f"Sources:\n{sources[:8000]}\n\nAnswer:\n{answer}",
                                 GradeResult, stage="grade_grounded", mock=mock)
    except Exception:  # noqa: BLE001
        return GradeResult.model_validate(mock())


def grade_policy_answer(pa: PolicyAnswer, llm: Optional[LLM] = None) -> PolicyAnswer:
    """Single-pass grade. Retry / widen / regenerate lives in PolicyLibrary.answer (M3)."""
    if pa.abstained or not pa.citations:
        return pa
    ctx = "\n\n".join(h.text for h in pa.citations)
    rel = grade_relevance(pa.question, ctx, llm)
    ground = grade_grounded(pa.answer, ctx, llm)
    pa.grader_relevant = rel.verdict
    pa.grader_grounded = ground.verdict
    if not pa.grader_relevant or not pa.grader_grounded:
        pa.abstained = True
        why = rel.reason if not pa.grader_relevant else ground.reason
        pa.answer = (
            "I found related policy text but could not produce an answer that is fully "
            f"supported by it ({why}). Please read the cited clauses directly."
        )
    return pa
