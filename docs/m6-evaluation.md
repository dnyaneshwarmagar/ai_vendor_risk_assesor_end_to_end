# Milestone 6 — Evaluate, write it up, demo

Deep Search Module 10 / Lab 11 · Production RAG Module 10 / Lab 10

## What shipped

| Deliverable | Where |
|-------------|--------|
| Real gold **10 vendors × 8 fields** (URL + `checked_on`) | `data/gold_set_real.json` |
| Mix of clear pass / clear fail / messy | `case_kind` on each case |
| LLM-as-judge for reasons + **20** hand labels | `eval/reason_judge.py`, `data/reason_faithfulness_labels.json` |
| Ablations (identity, reranker, freshness, planner) | `scripts/m6_ablation.py` → `reports/m6_ablation.md` |
| CI | `.github/workflows/ci.yml` (`pytest` + `run_eval.py --strict` + judge calibrate) |
| Offline + live scorecards | `reports/eval_report.md`, `reports/live_eval_report.md` |

## Commands

```bash
# Offline fictional gold (CI)
set LLM_PROVIDER=mock
set SEARCH_PROVIDER=offline
python -m pytest -q
python eval/run_eval.py --strict
python eval/reason_judge.py --calibrate --strict
python scripts/m6_ablation.py

# Live real gold (needs search + optional LLM)
python eval/run_live_eval.py --strict
python eval/field_accuracy.py --gold data/gold_set_real.json
```

## Ablation knobs

| Env | Default | Effect |
|-----|---------|--------|
| `VRA_IDENTITY_GATE` | `1` | Reject look-alike domains |
| `VRA_RERANKER` | `1` | Policy RAG reranker |
| `VRA_FRESHNESS_DECAY` | `1` | Half-life on claim scores |
| `VRA_LLM_PLAN` | `0` | LLM Plan Creator (slow); mock plan when off |

## Demo checklist

1. **Offline:** run LedgerLens from CLI or UI (`SEARCH_PROVIDER=offline`) → show BLOCKED + quarantine.
2. **Scorecard:** open `reports/eval_report.md` (accuracy, guess rate, safety, cost, latency).
3. **Ablation:** show identity row in `reports/m6_ablation.md` (UK ISO leak when gate OFF).
4. **Live:** one real vendor (e.g. Notion) with `ddgs`/`ollama` → field scorecard in live report.
5. **Honest miss:** call out a messy case (Anthropic India via Bedrock vs direct API) from gold notes.
