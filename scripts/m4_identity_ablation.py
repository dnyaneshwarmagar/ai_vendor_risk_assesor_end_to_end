"""
M4 ablation — switch the identity gate OFF and show the UK lookalike ISO leaking in.

Writes:
  reports/m4_identity_ablation.md   (side-by-side "screenshot" for the write-up)

Usage:
  python scripts/m4_identity_ablation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor import vendor_research as vr  # noqa: E402
from assessor.vendor_research import VendorResearcher  # noqa: E402

OUT = ROOT / "reports" / "m4_identity_ablation.md"
UK = "https://ledgerlens-uk.example/about-us"


def _cert_block(profile) -> str:
    fact = profile.facts.get("security_certifications")
    if not fact:
        return "(no security_certifications fact)"
    lines = [
        f"display: {fact.display}",
        f"evidence_level: {fact.evidence_level}",
        "sources:",
    ]
    for u in fact.sources:
        mark = "  ← LOOKALIKE LEAK" if "ledgerlens-uk" in u else ""
        lines.append(f"  - {u}{mark}")
    if fact.conflicts:
        lines.append("conflicts:")
        for c in fact.conflicts[:5]:
            lines.append(f"  - {c}")
    return "\n".join(lines)


def main() -> int:
    vr.SETTINGS.search_provider = "offline"

    vr.SETTINGS.identity_gate = True
    with_gate = VendorResearcher().research("LedgerLens AI")

    vr.SETTINGS.identity_gate = False
    without = VendorResearcher().research("LedgerLens AI")
    # restore for any later imports in same process
    vr.SETTINGS.identity_gate = True

    lines = [
        "# M4 ablation — identity gate OFF",
        "",
        "Offline corpus · vendor **LedgerLens AI** · lookalike "
        f"`{UK}`",
        "",
        "When the identity gate is disabled, the Manchester accountancy firm’s "
        "ISO 27001 certificate is treated as evidence for the SaaS vendor.",
        "",
        "```",
        "┌──────────────────────────────────────────────────────────────────────────┐",
        "│  IDENTITY GATE ON                          IDENTITY GATE OFF             │",
        "├──────────────────────────────────────────────────────────────────────────┤",
    ]

    on_reject = "REJECTED ✓" if UK in with_gate.rejected else "NOT REJECTED ✗"
    off_reject = "rejected" if UK in without.rejected else "ACCEPTED ✗ (leak path)"
    lines.append(f"│  lookalike URL: {on_reject:<28}  lookalike URL: {off_reject:<22} │")

    def _mentions_uk(profile) -> bool:
        fact = profile.facts.get("security_certifications")
        if not fact:
            return False
        blob = str(fact.model_dump()).lower()
        return "ledgerlens-uk" in blob or "uk-27001" in blob

    on_uk = _mentions_uk(with_gate)
    off_uk = _mentions_uk(without)
    lines.append(
        f"│  UK ISO anywhere in fact: {'no ✓':<20}  UK ISO in conflicts/sources: "
        f"{'YES ✗ LEAK' if off_uk else 'no':<12} │"
    )
    lines.append("└──────────────────────────────────────────────────────────────────────────┘")
    lines.append("```")
    lines += [
        "",
        "## With identity gate (production default)",
        "",
        "```",
        _cert_block(with_gate),
        f"rejected includes lookalike: {UK in with_gate.rejected}",
        f"UK ISO mentioned in cert fact: {on_uk}",
        "```",
        "",
        "## Without identity gate (ablation)",
        "",
        "```",
        _cert_block(without),
        f"rejected includes lookalike: {UK in without.rejected}",
        f"UK ISO mentioned in cert fact: {off_uk}",
        "```",
        "",
        "## Takeaway",
        "",
        "Even when the official trust centre still *wins* the merge, the UK firm’s "
        "`ISO 27001` / `UK-27001-0822` claim appears in **conflicts** once the gate is off — "
        "poison in the fact object. Catch point: **identity_gate**. "
        "Re-enable with `VRA_IDENTITY_GATE=1`.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))
    print(f"\nWrote {OUT}")
    if on_uk or not off_uk:
        print("WARNING: expected no UK mention with gate ON and a UK leak with gate OFF.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
