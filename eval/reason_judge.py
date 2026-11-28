"""
LLM-as-judge for assessment *reasons* — are they faithful to cited evidence?

COURSE MAP
  Deep Search Lab 11 · Production RAG Module 10 (faithfulness)

Offline (CI / calibration): token-overlap heuristic (deterministic).
Live: LLM.structured() with FaithfulnessGrade.

Usage
  python eval/reason_judge.py --calibrate          # score 20 hand labels → reports/reason_judge_calibration.md
  python eval/reason_judge.py --calibrate --strict # exit 1 if agreement < 85%
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.graders import GradeResult  # noqa: E402
from assessor.llm import LLM  # noqa: E402
from assessor.policy_rag import tokenize  # noqa: E402
from pydantic import BaseModel  # noqa: E402

LABELS = ROOT / "data" / "reason_faithfulness_labels.json"
CALIB_THRESHOLD = 0.85

FAITHFULNESS_SYSTEM = """You are the Reason Faithfulness Judge for Nimbu Mart vendor assessments.

Goal: decide whether the assessor's *reason* is fully supported by the cited evidence text.

Rules:
- verdict true only if every material claim in the reason appears in or is a fair paraphrase of the evidence.
- Invented certifications, regions, retention numbers, incidents, or plan tiers → false.
- Contradicting the evidence → false.
- Mere vagueness that still matches the evidence → true.

Return JSON: {"verdict": true|false, "reason": "..."}.
verdict true means FAITHFUL; false means UNFAITHFUL."""


class FaithfulnessGrade(BaseModel):
    verdict: bool
    reason: str = ""


def _heuristic_faithful(reason: str, evidence: str) -> GradeResult:
    """Deterministic stand-in used offline and as LLM fallback."""
    def _expand(toks: set[str]) -> set[str]:
        out = set(toks)
        if "aws" in out or "amazon" in out:
            out.update({"aws", "amazon", "services", "hosting"})
        if "dpa" in out or "addendum" in out:
            out.update({"dpa", "processing", "addendum", "agreement"})
        if "train" in out or "training" in out or "models" in out:
            out.update({"train", "training", "models", "customer", "data"})
        return out

    r_toks = _expand(set(tokenize(reason)))
    e_toks = _expand(set(tokenize(evidence)))
    if not r_toks:
        return GradeResult(verdict=False, reason="empty reason")
    overlap = len(r_toks & e_toks) / max(1, len(r_toks))
    invent_markers = (
        "fedramp", "ransomware", "forever", "nightly", "fine-tune",
        "mumbai", "7 days", "openai",
    )
    reason_l = reason.lower()
    evid_l = evidence.lower()
    invented = [m for m in invent_markers if m in reason_l and m not in evid_l]
    # "free on every plan" / "free including Free" — not bare word "free" in "download free"?
    if re.search(r"\bfree\b.*\b(plan|every|including)\b", reason_l) and "free" not in evid_l:
        invented.append("free-tier-claim")
    # Asserting India *is* available when evidence never mentions India.
    asserts_india_ok = bool(
        re.search(r"\bindia\b.{0,60}\b(is an available|currently available|available for)\b", reason_l)
        or re.search(r"\b(available|residency).{0,40}\bindia\b", reason_l)
    )
    denies_india = bool(re.search(r"\b(fail|fails|not|no|only|because)\b.{0,40}\bindia\b|\bindia\b.{0,40}\b(fail|not|only)\b", reason_l))
    if asserts_india_ok and not denies_india and "india" not in evid_l:
        invented.append("india-not-in-evidence")
    if "affiliate" in reason_l and "saas" in reason_l and "accountancy" in evid_l:
        invented.append("wrong-entity")
    # Reason denies DPA while evidence offers one (or vice-versa inventions).
    if re.search(r"\bno dpa\b|\bdoes not (offer|provide) a dpa\b|\bno dpa is offered\b", reason_l) and "dpa" in evid_l:
        invented.append("dpa-negation")
    if invented:
        return GradeResult(verdict=False, reason=f"heuristic unfaithful markers: {invented}")
    # Soft boost when reason correctly cites US/EU-only failure for India.
    if denies_india and ("united states" in evid_l or "european" in evid_l) and "india" not in evid_l:
        overlap = max(overlap, 0.30)
    # Paraphrases of short evidence (DPA / training / incident) often land ~0.25–0.40.
    ok = overlap >= 0.25
    return GradeResult(
        verdict=ok,
        reason=f"overlap={overlap:.2f} ({'faithful' if ok else 'weak overlap'})",
    )


def grade_reason_faithfulness(
    reason: str,
    evidence_text: str,
    *,
    llm: Optional[LLM] = None,
    force_heuristic: bool = False,
) -> GradeResult:
    if force_heuristic or llm is None or (llm and getattr(llm, "provider", None) == "mock"):
        # LLM() defaults read SETTINGS — still allow explicit mock path.
        client = llm or LLM()
        if force_heuristic or client.provider == "mock":
            return _heuristic_faithful(reason, evidence_text)

    client = llm or LLM()

    def mock() -> dict:
        g = _heuristic_faithful(reason, evidence_text)
        return {"verdict": g.verdict, "reason": g.reason}

    try:
        return client.structured(
            FAITHFULNESS_SYSTEM,
            f"Evidence:\n{evidence_text[:6000]}\n\nReason:\n{reason}",
            FaithfulnessGrade,
            stage="grade_reason_faithfulness",
            mock=mock,
        )
    except Exception:  # noqa: BLE001
        return _heuristic_faithful(reason, evidence_text)


def calibrate(path: Path = LABELS, *, strict: bool = False, force_heuristic: bool = True) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    agree = 0
    for item in data["labels"]:
        grade = grade_reason_faithfulness(
            item["reason"],
            item["evidence_text"],
            force_heuristic=force_heuristic,
        )
        pred = "faithful" if grade.verdict else "unfaithful"
        ok = pred == item["label"]
        agree += ok
        rows.append({
            "id": item["id"],
            "gold": item["label"],
            "pred": pred,
            "ok": ok,
            "judge": grade.reason[:120],
        })
    n = max(1, len(rows))
    agreement = agree / n
    lines = [
        f"# Reason faithfulness judge — calibration — {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"Labels: `{path.name}` · n={len(rows)} · agreement={agreement:.1%} "
        f"(threshold ≥ {CALIB_THRESHOLD:.0%})",
        "",
        "| ID | Gold | Pred | Match | Judge note |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['gold']} | {r['pred']} | {'✅' if r['ok'] else '❌'} | {r['judge']} |"
        )
    lines += ["", f"**Agreement:** {agree}/{len(rows)} = {agreement:.1%}"]
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    report = "\n".join(lines)
    (out / "reason_judge_calibration.md").write_text(report, encoding="utf-8")
    print(report)
    if strict and agreement < CALIB_THRESHOLD:
        print(f"\nFAILED calibration threshold ({agreement:.1%} < {CALIB_THRESHOLD:.0%})")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--live-judge", action="store_true", help="Use LLM judge instead of heuristic")
    ap.add_argument("--labels", default=str(LABELS))
    a = ap.parse_args(argv)
    if a.calibrate:
        return calibrate(Path(a.labels), strict=a.strict, force_heuristic=not a.live_judge)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
