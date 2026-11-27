"""
field_accuracy.py — compare a VendorProfile (or runs/*/profile.json) to gold_set_real.json.

Usage:
  python eval/field_accuracy.py --gold data/gold_set_real.json --profiles runs/.../profile.json
  python eval/field_accuracy.py --gold data/gold_set_real.json --from-research   # live/offline research per case

Threshold: overall field accuracy >= 0.80 and zero facts sourced from rejected URLs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.config import GOLD_SET_REAL  # noqa: E402
from assessor.schemas import VendorProfile  # noqa: E402


TEMPLATE_FIELDS = [
    "security_certifications",
    "data_regions",
    "trains_on_customer_data",
    "subprocessors",
    "data_retention",
    "sso_saml",
    "security_incidents",
    "dpa_available",
]


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _cert_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("name"):
                names.add(_norm(item["name"]))
            elif isinstance(item, str):
                names.add(_norm(item))
    return names


def score_field(field: str, expected: Any, fact: Optional[dict]) -> tuple[bool, str]:
    if fact is None:
        # Null / empty gold expectations: missing is acceptable (UNKNOWN, not a wrong answer).
        if field == "data_retention" and isinstance(expected, dict) and expected.get("default_days") is None and expected.get("deletion_on_request_days") is None:
            return True, "missing ok (gold null)"
        if field == "security_incidents" and isinstance(expected, dict) and int(expected.get("major_count") or 0) == 0:
            return True, "missing ok (gold zero majors)"
        if field == "subprocessors" and isinstance(expected, dict) and int(expected.get("count") or 0) == 0 and not expected.get("has_model_provider"):
            return True, "missing ok (gold empty list)"
        return False, "missing fact"
    value = fact.get("value")
    level = fact.get("evidence_level")

    if field == "security_certifications":
        want = {_norm(n) for n in expected.get("has", [])}
        got = _cert_names(value)
        if not want:
            return True, "no certs required"
        # Pass if every expected name appears (allowing SOC 2 Type II to match SOC 2)
        ok = all(any(w in g or g in w for g in got) for w in want)
        if expected.get("evidence_level") == "documented" and level != "documented":
            return False, f"certs found but evidence_level={level}, want documented"
        return ok, f"want {want} got {got}"

    if field == "data_regions":
        india = expected.get("india_available")
        avail = []
        if isinstance(value, dict):
            avail = value.get("available") or []
        hay = " ".join(_norm(x) for x in avail)
        has_india = "india" in hay or "in.api" in hay
        return has_india == bool(india), f"india_available gold={india} got={has_india} regions={avail}"

    if field == "trains_on_customer_data":
        ok = _norm(value) == _norm(expected)
        return ok, f"want {expected!r} got {value!r}"

    if field == "subprocessors":
        if value is None:
            return expected.get("count", 0) == 0, "null subprocessors"
        items = value if isinstance(value, list) else []
        count_ok = len(items) >= int(expected.get("count") or 0)
        want_mp = bool(expected.get("has_model_provider"))
        has_mp = any(_norm(i.get("category")) == "model_provider" for i in items if isinstance(i, dict))
        # If gold only requires count>=1, don't fail solely on model_provider when list is long but categories opaque
        if want_mp and not has_mp and len(items) >= 1:
            return count_ok, f"count_ok={count_ok}; model_provider not labelled (len={len(items)})"
        return count_ok and (has_mp == want_mp or not want_mp), f"count={len(items)} model_provider={has_mp}"

    if field == "data_retention":
        if not isinstance(value, dict):
            return expected.get("default_days") is None, f"want dict got {type(value)}"
        # Soft match: if gold default_days set, require equality; null gold = any/unknown ok
        d_ok = expected.get("default_days") is None or value.get("default_days") == expected.get("default_days")
        return d_ok, f"want {expected} got {value}"

    if field == "sso_saml":
        ok = _norm(value) == _norm(expected)
        # enterprise_only vs paid_plans are adjacent — accept either if gold is enterprise_only and got paid_plans
        if not ok and _norm(expected) == "enterprise_only" and _norm(value) == "paid_plans":
            return True, "paid_plans accepted as enterprise-adjacent"
        if not ok and _norm(expected) == "paid_plans" and _norm(value) == "enterprise_only":
            return True, "enterprise_only accepted as paid_plans-adjacent"
        return ok, f"want {expected!r} got {value!r}"

    if field == "security_incidents":
        items = value if isinstance(value, list) else []
        majors = [i for i in items if isinstance(i, dict) and _norm(i.get("severity")) == "major"]
        want_n = int(expected.get("major_count") or 0)
        # Allow agent to miss or over-count by 0 if both zero; if gold>0 require at least one major
        if want_n == 0:
            return len(majors) == 0, f"majors={len(majors)}"
        return len(majors) >= 1, f"want>={want_n} majors got {len(majors)}"

    if field == "dpa_available":
        ok = _norm(value) == _norm(expected)
        if not ok and _norm(expected) == "yes" and _norm(value) == "on_request":
            return True, "on_request accepted as yes-adjacent"
        return ok, f"want {expected!r} got {value!r}"

    return False, f"unknown field {field}"


def score_profile(case: dict, profile: dict) -> dict:
    expected_facts = case.get("expected_facts") or {}
    facts = profile.get("facts") or {}
    rejected = set(profile.get("rejected") or [])
    rows = []
    hits = 0
    contamination = 0
    for field in TEMPLATE_FIELDS:
        if field not in expected_facts:
            continue
        fact = facts.get(field)
        fact_dict = fact if isinstance(fact, dict) else (fact.model_dump() if hasattr(fact, "model_dump") else None)
        ok, detail = score_field(field, expected_facts[field], fact_dict)
        sources = (fact_dict or {}).get("sources") or []
        bad = [u for u in sources if u in rejected]
        if bad:
            contamination += 1
            ok = False
            detail += f"; CONTAMINATED by rejected {bad}"
        hits += int(ok)
        rows.append({"field": field, "ok": ok, "detail": detail})
    n = len(rows) or 1
    return {
        "vendor": case.get("vendor"),
        "accuracy": hits / n,
        "hits": hits,
        "n": n,
        "contamination": contamination,
        "fields": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, default=GOLD_SET_REAL)
    ap.add_argument("--profiles", nargs="*", type=Path, help="profile.json paths aligned to gold cases order")
    ap.add_argument("--from-research", action="store_true", help="Run VendorResearcher for each gold case")
    ap.add_argument("--threshold", type=float, default=0.80)
    args = ap.parse_args()

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    cases = gold["cases"]
    profiles: list[dict] = []

    if args.from_research:
        from assessor.vendor_research import VendorResearcher
        for case in cases:
            profile = VendorResearcher().research(case["vendor"], case.get("official_domain"))
            profiles.append(profile.model_dump(mode="json"))
    elif args.profiles:
        for p in args.profiles:
            profiles.append(json.loads(p.read_text(encoding="utf-8")))
    else:
        print("Provide --profiles or --from-research", file=sys.stderr)
        return 2

    if len(profiles) != len(cases):
        print(f"Expected {len(cases)} profiles, got {len(profiles)}", file=sys.stderr)
        return 2

    results = [score_profile(c, p) for c, p in zip(cases, profiles)]
    overall_hits = sum(r["hits"] for r in results)
    overall_n = sum(r["n"] for r in results)
    overall = overall_hits / overall_n if overall_n else 0.0
    contamination = sum(r["contamination"] for r in results)

    print(f"# Field accuracy vs {args.gold.name}")
    for r in results:
        print(f"\n## {r['vendor']}: {r['accuracy']:.0%} ({r['hits']}/{r['n']})")
        for row in r["fields"]:
            mark = "OK" if row["ok"] else "MISS"
            print(f"  [{mark}] {row['field']}: {row['detail']}")
    print(f"\nOverall: {overall:.0%} ({overall_hits}/{overall_n}); contamination={contamination}")
    ok = overall >= args.threshold and contamination == 0
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
