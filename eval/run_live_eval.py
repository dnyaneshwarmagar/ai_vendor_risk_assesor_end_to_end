"""
run_live_eval.py — live LLM + live web scorecard (Milestone 2/3).

Does NOT use SEARCH_PROVIDER=offline or LLM_PROVIDER=mock.
Scores:
  1) LLM routing accuracy on data/routing_gold.json (≥ 90%)
  2) Real-vendor field accuracy on data/gold_set_real.json (≥ 80%, contamination 0)
  3) Live policy Q&A soft/hard checks from data/gold_set.json (informational)

Usage:
  python eval/run_live_eval.py
  python eval/run_live_eval.py --strict
  python eval/run_live_eval.py --skip-vendors   # routing + policy only (faster)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force live before assessor.config loads settings from a stale process — caller should set .env;
# we still refuse to run if offline/mock.
os.environ.pop("VRA_FORCE_LLM_ROUTER", None)  # ddgs already enables LLM router

from assessor.config import GOLD_SET, GOLD_SET_REAL, SETTINGS  # noqa: E402
from assessor.graph import Pipeline  # noqa: E402
from assessor.llm import LLM  # noqa: E402
from assessor.router import decide  # noqa: E402
from assessor.tracing import Budget, Tracer  # noqa: E402
from assessor.vendor_research import VendorResearcher  # noqa: E402
from eval.field_accuracy import score_profile  # noqa: E402

ROUTING_GOLD = ROOT / "data" / "routing_gold.json"
OUT = ROOT / "reports" / "live_eval_report.md"


def _require_live() -> None:
    if SETTINGS.llm_provider == "mock":
        raise SystemExit("Live eval needs LLM_PROVIDER≠mock (e.g. ollama). Update .env.")
    if SETTINGS.search_provider == "offline":
        raise SystemExit("Live eval needs SEARCH_PROVIDER=ddgs or tavily (not offline). Update .env.")


def eval_routing() -> dict:
    gold = json.loads(ROUTING_GOLD.read_text(encoding="utf-8"))
    vendors = gold.get("known_vendors") or []
    llm = LLM()
    hits = 0
    rows = []
    for case in gold["cases"]:
        d = decide(case["question"], vendors, llm, force_llm=True)
        ok = d.route == case["route"]
        hits += int(ok)
        rows.append({"id": case["id"], "expected": case["route"], "got": d.route, "ok": ok,
                     "q": case["question"]})
    n = len(gold["cases"]) or 1
    return {"accuracy": hits / n, "hits": hits, "n": n, "rows": rows}


def eval_real_vendors(max_usd: float) -> dict:
    gold = json.loads(GOLD_SET_REAL.read_text(encoding="utf-8"))
    results = []
    profiles = []
    for case in gold["cases"]:
        budget = Budget(max_usd=max_usd)
        tracer = Tracer(f"live-{case['id']}", enabled=True)
        t0 = time.time()
        try:
            profile = VendorResearcher(budget=budget, tracer=tracer).research(
                case["vendor"], case.get("official_domain"))
        except Exception as exc:  # noqa: BLE001
            results.append({"vendor": case["vendor"], "error": str(exc), "accuracy": 0.0,
                            "hits": 0, "n": 8, "contamination": 1, "elapsed_s": time.time() - t0,
                            "spent": budget.spent_usd})
            continue
        elapsed = time.time() - t0
        pdata = profile.model_dump(mode="json")
        (tracer.dir / "profile.json").write_text(json.dumps(pdata, indent=2), encoding="utf-8")
        scored = score_profile(case, pdata)
        scored["elapsed_s"] = elapsed
        scored["spent"] = budget.spent_usd
        scored["pages"] = profile.pages_read
        results.append(scored)
        profiles.append(str(tracer.dir / "profile.json"))
    overall_hits = sum(r.get("hits", 0) for r in results)
    overall_n = sum(r.get("n", 0) for r in results) or 1
    return {
        "accuracy": overall_hits / overall_n,
        "hits": overall_hits,
        "n": overall_n,
        "contamination": sum(r.get("contamination", 0) for r in results),
        "vendors": results,
        "profiles": profiles,
        "max_elapsed": max((r.get("elapsed_s") or 0) for r in results) if results else 0,
        "total_spent": sum(r.get("spent") or 0 for r in results),
    }


def eval_policy_qa() -> dict:
    gold = json.loads(GOLD_SET.read_text(encoding="utf-8"))
    pipe = Pipeline(tracer=None, budget=Budget(max_usd=2.0))
    hard_ok = hard_n = soft_ok = soft_n = 0
    rows = []
    for pq in gold.get("policy_questions", []):
        pa = pipe.library.answer(pq["question"], pq["user_groups"], llm=pipe.llm)
        cited_docs = {c.doc for c in pa.citations}
        top = pa.citations[0] if pa.citations else None
        checks = []
        if "must_not_cite_doc" in pq:
            ok = pq["must_not_cite_doc"] not in cited_docs
            hard_n += 1
            hard_ok += int(ok)
            checks.append(("must_not_cite", ok))
        if "expected_clause" in pq:
            ok = top is not None and top.clause_id == pq["expected_clause"]
            soft_n += 1
            soft_ok += int(ok)
            checks.append((f"clause={pq['expected_clause']}", ok))
        for word in pq.get("expected_answer_contains", []):
            ok = (not pa.abstained) and word.lower() in pa.answer.lower()
            soft_n += 1
            soft_ok += int(ok)
            checks.append((f"has '{word}'", ok))
        rows.append({"id": pq["id"], "abstained": pa.abstained, "checks": checks,
                     "relevant": pa.grader_relevant, "grounded": pa.grader_grounded})
    return {
        "hard": hard_ok / max(1, hard_n),
        "soft": soft_ok / max(1, soft_n),
        "rows": rows,
        "spent": pipe.budget.spent_usd,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--skip-routing", action="store_true")
    ap.add_argument("--skip-vendors", action="store_true")
    ap.add_argument("--skip-policy", action="store_true")
    ap.add_argument("--max-usd", type=float, default=float(os.environ.get("VRA_MAX_USD") or "0.50"))
    args = ap.parse_args()
    _require_live()

    t0 = time.time()
    lines = [
        f"# Live evaluation — {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"LLM_PROVIDER={SETTINGS.llm_provider} · LLM_MODEL={SETTINGS.llm_model or '(default)'} · "
        f"LLM_SMALL_MODEL={SETTINGS.llm_small_model or '(same)'} · SEARCH_PROVIDER={SETTINGS.search_provider}",
        "",
        "## Scorecard",
        "",
        "| Metric | Value | Threshold | Status |",
        "|---|---|---|---|",
    ]
    status: dict[str, bool] = {}

    routing = None
    if not args.skip_routing:
        print("=== 1/3 LLM routing ===", flush=True)
        routing = eval_routing()
        ok = routing["accuracy"] >= 0.90
        status["routing"] = ok
        lines.append(f"| routing_accuracy (LLM) | {routing['accuracy']:.0%} ({routing['hits']}/{routing['n']}) | ≥ 90% | {'✅' if ok else '❌'} |")
        print(f"routing: {routing['accuracy']:.0%}", flush=True)
    else:
        lines.append("| routing_accuracy (LLM) | skipped | ≥ 90% | — |")

    vendors = None
    if not args.skip_vendors:
        print("=== 2/3 Real-vendor research (live web) ===", flush=True)
        vendors = eval_real_vendors(args.max_usd)
        ok_f = vendors["accuracy"] >= 0.80 and vendors["contamination"] == 0
        status["field_accuracy"] = ok_f
        lines.append(
            f"| field_accuracy (real vendors) | {vendors['accuracy']:.0%} ({vendors['hits']}/{vendors['n']}) | ≥ 80% | "
            f"{'✅' if ok_f else '❌'} |"
        )
        lines.append(f"| contamination | {vendors['contamination']} | = 0 | {'✅' if vendors['contamination'] == 0 else '❌'} |")
        lines.append(f"| vendor research cost | ${vendors['total_spent']:.4f} | under budget | — |")
        lines.append(f"| slowest vendor | {vendors['max_elapsed']:.1f}s | < 90s target | {'✅' if vendors['max_elapsed'] < 90 else '⚠️'} |")
        print(f"fields: {vendors['accuracy']:.0%} contamination={vendors['contamination']}", flush=True)
    else:
        lines.append("| field_accuracy (real vendors) | skipped | ≥ 80% | — |")

    policy = None
    if not args.skip_policy:
        print("=== 3/3 Live policy Q&A ===", flush=True)
        policy = eval_policy_qa()
        ok_h = policy["hard"] >= 1.0
        status["policy_qa_hard"] = ok_h
        lines.append(f"| policy_qa_hard | {policy['hard']:.0%} | ≥ 100% | {'✅' if ok_h else '❌'} |")
        lines.append(f"| policy_qa_soft | {policy['soft']:.0%} | informational | — |")
        lines.append(f"| policy LLM cost | ${policy['spent']:.4f} | — | — |")
        print(f"policy hard={policy['hard']:.0%} soft={policy['soft']:.0%}", flush=True)
    else:
        lines.append("| policy_qa | skipped | — | — |")

    lines.append(f"| wall time | {time.time() - t0:.1f}s | — | — |")
    if routing is not None:
        lines += ["", "## Routing misses"]
        misses = [r for r in routing["rows"] if not r["ok"]]
        if not misses:
            lines.append("None.")
        else:
            for r in misses:
                lines.append(f"- `{r['id']}` expected `{r['expected']}` got `{r['got']}` — {r['q']}")

    if vendors:
        lines += ["", "## Real vendors"]
        for r in vendors["vendors"]:
            if r.get("error"):
                lines.append(f"- **{r['vendor']}**: ERROR {r['error']}")
                continue
            lines.append(
                f"- **{r['vendor']}**: {r['accuracy']:.0%} ({r['hits']}/{r['n']}), "
                f"pages={r.get('pages')}, {r.get('elapsed_s', 0):.1f}s, ${r.get('spent', 0):.4f}"
            )
            for f in r.get("fields") or []:
                mark = "OK" if f["ok"] else "MISS"
                lines.append(f"  - [{mark}] {f['field']}: {f['detail']}")

    if policy:
        lines += ["", "## Policy questions"]
        for r in policy["rows"]:
            chk = ", ".join(f"{'✓' if ok else '✗'} {n}" for n, ok in r["checks"])
            lines.append(f"- `{r['id']}` abstain={r['abstained']} rel={r['relevant']} ground={r['grounded']} — {chk}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {OUT}")

    if args.strict and any(not v for v in status.values()):
        print("FAILED:", [k for k, v in status.items() if not v])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
