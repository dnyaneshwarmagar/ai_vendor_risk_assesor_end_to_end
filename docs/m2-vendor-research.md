# Milestone 2 — Planned parallel vendor research

## What changed

- [`assessor/vendor_research.py`](../assessor/vendor_research.py) live path is no longer a sequential baseline. It now runs **Plan Creator → Plan Reviewer → parallel workers → evaluate_progress**, sharing one [`Budget`](../assessor/tracing.py), and still emits the same `VendorProfile` as offline mode.
- **Module 12 place 2:** every entry in `AUTHORITY`, `FIELD_AUTHORITY_OVERRIDES`, and `HALF_LIFE_DAYS` has a comment justifying the number for AI/SaaS due diligence.
- **Planning (Lab 3):** one sub-question per `VENDOR_FIELDS` entry plus an entity lens. Stop when every high-stakes field has a **documented** source, or **two searches** for that field have failed (also: max iterations, budget nearly exhausted, no new evidence).
- **Parallel executor (Lab 4 / 10):** `ThreadPoolExecutor` with `VRA_MAX_PARALLEL`; search → fetch → **identity gate** → injection quarantine → extract. Extraction and identity use **`LLM.small`**; plan create uses the main model.
- **Identity gate:** live LLM decides “same company?” from **domain, legal entity, and product**. Reject only — never down-weight. Offline corpus still uses deterministic `about_entity`.
- **Stretch:** [`data/vendor_memory/`](../data/vendor_memory/) remembers URLs / rejected hosts so a re-review can skip unchanged live fetches (SEC-12.1). [`cached_pages/`](../cached_pages/) holds HTML/text snapshots for demos without the open internet (`VRA_PAGE_CACHE=1` or `SEARCH_PROVIDER=cache`).
- Planning contracts added in [`assessor/schemas.py`](../assessor/schemas.py): `EntityAnchor`, `SubQuestion`, `ResearchPlan`, `PlanReview`, `PlanDecision`.
- Hand gold: [`data/gold_set_real.json`](../data/gold_set_real.json) (Notion, OpenAI, HubSpot). Scorer: [`eval/field_accuracy.py`](../eval/field_accuracy.py).
- Offline regression suite unchanged: fictional corpus + `pytest tests` + `eval/run_eval.py --strict`.

## Model routing (Ollama)

| Role | Env | Example | Used for |
|------|-----|---------|----------|
| Main | `LLM_MODEL` | `qwen2.5:7b` | Plan Creator |
| Small | `LLM_SMALL_MODEL` | `qwen2.5:3b` | Identity gate + claim extraction (many calls per run) |

```bash
ollama pull qwen2.5:7b
ollama pull qwen2.5:3b
```

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
LLM_SMALL_MODEL=qwen2.5:3b
LLM_TEMPERATURE=0
```

## Local setup — offline CI (unchanged)

```env
SEARCH_PROVIDER=offline
# LLM can stay ollama for policy answers; vendor facts still come from mock_claims
```

```bash
python -m pytest tests -q
python eval/run_eval.py --strict
```

## Local setup — real-vendor demo (no open internet)

Uses snapshots under `cached_pages/` and rule/LLM extract on the live path shape:

```env
LLM_PROVIDER=mock          # or ollama + LLM_SMALL_MODEL for real extract/identity
SEARCH_PROVIDER=cache
VRA_PAGE_CACHE=1
VRA_VENDOR_MEMORY=1
VRA_MAX_USD=0.50
```

```bash
python scripts/m2_cache_run.py
# or manually:
# python eval/field_accuracy.py --gold data/gold_set_real.json --profiles runs/.../profile.json ...
```

Expect: overall field accuracy **≥ 80%**, **contamination = 0** (no fact sourced from a rejected URL).

## Local setup — live web

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
LLM_SMALL_MODEL=qwen2.5:3b
SEARCH_PROVIDER=ddgs       # or tavily + TAVILY_API_KEY
VRA_MAX_USD=0.50
VRA_MAX_PARALLEL=4
# optional: VRA_PAGE_CACHE=1 to prefer cached_pages/ when present
```

```bash
pip install openai ddgs trafilatura httpx
python run_assessor.py "Can our support team use Notion for ticket notes?" \
  --vendor Notion --domain notion.com --tier T3 --users 35 --max-usd 0.50
```

Done when (brief): field accuracy ≥ 80% on the three gold vendors, no cross-company contamination, cost under `VRA_MAX_USD`, wall time under 90s, offline tests still green.

## Key files

| Path | Role |
|------|------|
| [`assessor/vendor_research.py`](../assessor/vendor_research.py) | Planner, parallel gather, gate, memory, cache |
| [`assessor/schemas.py`](../assessor/schemas.py) | Vendor fields + planning models |
| [`data/gold_set_real.json`](../data/gold_set_real.json) | Hand-filled real-vendor gold |
| [`eval/field_accuracy.py`](../eval/field_accuracy.py) | Field accuracy scorecard |
| [`cached_pages/`](../cached_pages/) | Demo page snapshots |
| [`data/vendor_memory/`](../data/vendor_memory/) | Per-domain URL memory |
| [`tests/test_vendor_research_m2.py`](../tests/test_vendor_research_m2.py) | Mocked planner / stop / gate tests |
| [`scripts/m2_cache_run.py`](../scripts/m2_cache_run.py) | Cache research + field_accuracy for the three vendors |
