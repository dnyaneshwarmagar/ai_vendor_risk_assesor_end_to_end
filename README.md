# AI Vendor Risk Assessor

**Capstone · Nimbu Mart Information Security**

> *"Can our support team use LedgerLens AI with customer tickets?"*

The assessor reads our policies, researches the vendor on the web, checks every requirement **deterministically**, drafts vendor questions, and hands a review file to a human. It never approves anything itself.

---

## The problem

Security and procurement teams spend days chasing trust-centre PDFs, residency pages and DPAs for every SaaS tool. Mistakes look like: trusting a look-alike domain, treating marketing “SOC 2” copy as evidence, or guessing PASS when the page never stated India residency. We need a system that is **fast enough to demo**, **strict enough for DP-3.1**, and **honest about UNKNOWN**.

## Architecture

```
Question → Router → Policy RAG  and/or  Vendor Deep Search → Matcher → Report → Human gate
                         │                      │
                    ACL + rerank          identity · quarantine · freshness · merge
                         │                      │
                         └──────── LangGraph (interrupt) + RQ + Postgres (M5) ──┘
```

| Layer | Role |
|-------|------|
| **Policy RAG** | Clause chunks, hybrid retrieval, optional reranker, graders, ACL |
| **Vendor research** | Plan → search → identity gate → injection quarantine → extract → authority×freshness → merge |
| **Matcher** | Requirement × fact → PASS/FAIL/UNKNOWN (no LLM verdicts) |
| **Product (M5)** | FastAPI + Streamlit, Redis/RQ queue, Neon Postgres history, `interrupt()` approval |

Offline defaults: `LLM_PROVIDER=mock`, `SEARCH_PROVIDER=offline` (fictional corpus). Live: Ollama/Gemini/… + `ddgs`/`tavily`, cloud Neon + Upstash optional.

## The numbers (latest offline / live scorecards)

| Metric | Fictional (`gold_set.json`) | Real (`gold_set_real.json`, 10×8) |
|--------|-----------------------------|----------------------------------|
| Verdict / field accuracy | see `reports/eval_report.md` (≥95% verdicts) | see `reports/live_eval_report.md` / `field_accuracy` |
| Guess rate | ≤ 0% (UNKNOWN must stay UNKNOWN) | contamination = 0 |
| Safety | quarantine / reject / rumour expectations | injection must not leak |
| Cost / latency | mock ≈ $0; wall time in report | budget `VRA_MAX_USD`; slowest vendor target &lt; 90s |
| Reason faithfulness | judge calibrated ≥85% on 20 labels (`reports/reason_judge_calibration.md`) | LLM judge optional live |

Ablations (each must earn its place): `reports/m6_ablation.md` — identity gate, reranker, freshness decay, planner.

## What went wrong (honest failures)

- **JS trust centres** (Notion/Wolfia, SafeBase): scrapers see shells; cache + hand gold URLs matter.
- **India residency ambiguity**: Anthropic direct API vs Bedrock India profiles — gold scores the surface you asked about.
- **RQ 3.0**: `Connection` context manager removed; worker now passes `connection=` explicitly.
- **Latency**: live Plan Creator on local 7B was minutes; default `VRA_LLM_PLAN=0` keeps field coverage via mock plan.
- **Judge calibration**: pure token overlap under-called paraphrases; markers + light synonym expand brought offline agreement to ≥85%.

## What we would do next

1. Shared LangGraph checkpointer (Postgres) for multi-host workers.
2. Stronger live reason-judge with disagreement review UI.
3. Expand real gold beyond 10 as residency pages change; automate link rot checks.
4. Host API/UI (Railway/Fly) in front of Neon + claimed Upstash.

---

## Setup

Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env
python scripts/check_setup.py
```

## Run offline (demo day one)

```bash
python run_assessor.py               # LedgerLens T3 → BLOCKED + quarantine
python -m pytest -q
python eval/run_eval.py --strict
python eval/reason_judge.py --calibrate --strict
python scripts/m6_ablation.py
```

Product UI (optional Redis/Postgres — see `docs/m5-product.md`):

```bash
uvicorn app.api:app --port 8000
python -m app.worker                 # when VRA_INLINE_QUEUE=0
streamlit run app/ui.py
```

## Live

```bash
# .env: LLM_PROVIDER=ollama, SEARCH_PROVIDER=ddgs, …
python run_assessor.py "Can support use Notion for ticket notes?" --vendor Notion --domain notion.com --tier T3 --users 35
python eval/run_live_eval.py --strict
```

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push/PR:

- `pytest -q`
- `eval/run_eval.py --strict` (fictional gold)
- `eval/reason_judge.py --calibrate --strict`

## Docs map

| Doc | Milestone |
|-----|-----------|
| `docs/m1-policy-rag.md` … `m5-product.md` | M1–M5 |
| `docs/m6-evaluation.md` | evaluation, judge, ablations, demo checklist |
| `docs/code-flow.md` | end-to-end flow |

## Project rules

1. **The LLM never decides a verdict** — `matcher.py` does.
2. **UNKNOWN beats a guess.**
3. **A claim is not evidence** (`claimed` vs `documented`).
4. **Identity is a gate**; injection pages are quarantined.
5. **ACL lives in retrieval.**
6. **Humans approve.**

All companies and documents under `data/policies` and the offline vendor corpus are fictional training material. Real-vendor gold URLs in `data/gold_set_real.json` were hand-checked; do not overwrite them with agent output.
