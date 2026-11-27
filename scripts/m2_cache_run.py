"""Run live-path research against cached_pages/ for the three M2 gold vendors."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("SEARCH_PROVIDER", "cache")
os.environ.setdefault("VRA_PAGE_CACHE", "1")
os.environ.setdefault("VRA_VENDOR_MEMORY", "1")

from assessor.tracing import Budget, Tracer
from assessor.vendor_research import VendorResearcher

VENDORS = [("Notion", "notion.com"), ("OpenAI", "openai.com"), ("HubSpot", "hubspot.com")]


def main() -> None:
    paths = []
    for name, dom in VENDORS:
        budget = Budget(max_usd=0.5)
        tracer = Tracer(f"m2-{dom.split('.')[0]}", enabled=True)
        researcher = VendorResearcher(budget=budget, tracer=tracer)
        start = time.time()
        profile = researcher.research(name, dom)
        elapsed = time.time() - start
        out = tracer.dir / "profile.json"
        out.write_text(json.dumps(profile.model_dump(mode="json"), indent=2), encoding="utf-8")
        paths.append(str(out))
        print(
            f"{name}: facts={list(profile.facts)} spent=${budget.spent_usd:.4f} "
            f"elapsed={elapsed:.2f}s pages={profile.pages_read} rejected={len(profile.rejected)}"
        )
    print("PROFILES", json.dumps(paths))
    from eval.field_accuracy import main as score_main
    import sys
    sys.argv = ["field_accuracy", "--gold", "data/gold_set_real.json", "--profiles", *paths]
    raise SystemExit(score_main())


if __name__ == "__main__":
    main()
