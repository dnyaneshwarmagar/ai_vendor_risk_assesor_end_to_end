"""
run_routing_eval.py — Milestone 3 routing accuracy (mock vs LLM).

  python eval/run_routing_eval.py                  # mock router only
  python eval/run_routing_eval.py --llm            # force LLM router (needs live LLM_PROVIDER)
  python eval/run_routing_eval.py --both --strict  # compare; exit 1 if LLM < 90%
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assessor.config import DATA_DIR  # noqa: E402
from assessor.llm import LLM  # noqa: E402
from assessor.router import decide  # noqa: E402

GOLD = DATA_DIR / "routing_gold.json"
THRESHOLD = 0.90


def score(cases: list[dict], vendors: list[str], *, force_llm: bool) -> dict:
    llm = LLM()
    rows = []
    hits = 0
    for case in cases:
        d = decide(case["question"], vendors, llm, force_llm=force_llm)
        ok = d.route == case["route"]
        hits += int(ok)
        rows.append({
            "id": case["id"],
            "expected": case["route"],
            "got": d.route,
            "ok": ok,
            "reason": d.reason,
            "question": case["question"],
        })
    n = len(cases) or 1
    return {"accuracy": hits / n, "hits": hits, "n": n, "rows": rows,
            "mode": "llm" if force_llm and not llm.mock_mode else "mock"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, default=GOLD)
    ap.add_argument("--llm", action="store_true", help="Force LLM router (VRA_FORCE_LLM_ROUTER)")
    ap.add_argument("--both", action="store_true", help="Score mock and LLM")
    ap.add_argument("--strict", action="store_true", help="Exit 1 if LLM accuracy < 90%")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "routing_eval.md")
    args = ap.parse_args()

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    vendors = gold.get("known_vendors") or []
    cases = gold["cases"]

    modes = []
    if args.both:
        modes = [False, True]
    elif args.llm:
        modes = [True]
    else:
        modes = [False]

    lines = ["# Routing evaluation (Milestone 3)", ""]
    llm_acc = None
    exit_code = 0

    for force in modes:
        result = score(cases, vendors, force_llm=force)
        if result["mode"] == "llm":
            llm_acc = result["accuracy"]
        lines.append(f"## Mode: {result['mode']}")
        lines.append(f"Accuracy: **{result['accuracy']:.0%}** ({result['hits']}/{result['n']})")
        lines.append("")
        lines.append("| Id | Expected | Got | OK | Question |")
        lines.append("|---|---|---|---|---|")
        for r in result["rows"]:
            mark = "✓" if r["ok"] else "✗"
            q = r["question"].replace("|", "/")
            lines.append(f"| {r['id']} | {r['expected']} | {r['got']} | {mark} | {q} |")
        misses = [r for r in result["rows"] if not r["ok"]]
        if misses:
            lines.append("")
            lines.append("### Misses")
            for r in misses:
                lines.append(f"- `{r['id']}` expected `{r['expected']}` got `{r['got']}` — {r['reason']}")
        lines.append("")
        print(f"{result['mode']}: {result['accuracy']:.0%} ({result['hits']}/{result['n']})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")

    if args.strict and llm_acc is not None and llm_acc < THRESHOLD:
        print(f"FAIL: LLM routing accuracy {llm_acc:.0%} < {THRESHOLD:.0%}")
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
