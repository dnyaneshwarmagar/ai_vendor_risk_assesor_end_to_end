# Milestone 3 — Router and graders as agents

## What changed

- [`assessor/router.py`](../assessor/router.py): LLM Router with goal/backstory ported from the Agentic RAG kit (`agents.py` / `tasks.py`). Four routes — `policy`, `vendor`, `assessment`, `refuse` — return `RouteDecision` via `LLM.structured()`. Offline/CI keeps the regex mock unless `force_llm=True` or `VRA_FORCE_LLM_ROUTER=1`.
- [`assessor/graders.py`](../assessor/graders.py): Answer Grader (`grade_relevance`) and Hallucination Grader (`grade_grounded`) with kit-style prompts.
- [`assessor/policy_rag.py`](../assessor/policy_rag.py) live answer retry loop:
  1. retrieve → generate
  2. **not relevant** → widen to **k=8** + `multi_query` rewrite → regenerate
  3. **not grounded** → regenerate once with `POLICY_SYSTEM_STRICT` → else **abstain**
- [`assessor/graph.py`](../assessor/graph.py): grades extractive/mock answers only when the live loop has not already graded.
- Routing gold: [`data/routing_gold.json`](../data/routing_gold.json) — 30 questions (10 policy / 10 vendor / 10 assessment), including awkward cases.
- Scorer: [`eval/run_routing_eval.py`](../eval/run_routing_eval.py) → [`reports/routing_eval.md`](../reports/routing_eval.md).

## Awkward cases (semantic meaning)

| Question | Route | Why |
|----------|-------|-----|
| “Is LedgerLens AI SOC 2 so we can use it?” | **assessment** | Vendor fact + use decision → policy + research |
| “Which tier is Parakeet approved for?” | **policy** | Asks what *our* AVL says, not the public web |

## Break the Router on purpose (course exercise)

In the Agentic RAG kit, deleting *“You make routing decisions based on the semantic MEANING of the question, not just on matching keywords.”* makes the Router latch onto surface words (e.g. “SOC 2” → always vendor).

**What we changed**

1. Kept that sentence in `ROUTER_SYSTEM` and added worked examples of awkward questions.
2. Regex mock gained `\bso we can use\b` so offline also treats “SOC 2 so we can use it” as assessment.
3. `guess_vendor` sorts names by length so longer vendor strings win.

**Reproduce the break:** remove the MEANING sentence → `VRA_FORCE_LLM_ROUTER=1 python eval/run_routing_eval.py --llm` → expect misses on `a04` / `p03` / `p08` → restore and re-run.

## Hallucination → abstain

An invented clause (e.g. `FAKE-9.9`) fails `grade_grounded`; the live loop / `grade_policy_answer` sets `abstained=True`. Covered by [`tests/test_graders_m3.py`](../tests/test_graders_m3.py).

## Local setup

```bash
ollama pull qwen2.5:7b
```

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
LLM_SMALL_MODEL=qwen2.5:3b
SEARCH_PROVIDER=offline
# VRA_FORCE_LLM_ROUTER=1   # use LLM router while search stays offline (M3 benchmark)
```

## Verify

Offline CI (fictional gold — keep `SEARCH_PROVIDER=offline` for this):

```bash
python -m pytest tests -q
python eval/run_eval.py --strict
python eval/run_routing_eval.py
```

Live LLM + live web (Ollama + ddgs):

```powershell
$env:LLM_PROVIDER='ollama'
$env:LLM_MODEL='qwen2.5:7b'
$env:LLM_SMALL_MODEL='qwen2.5:3b'
$env:SEARCH_PROVIDER='ddgs'
$env:PYTHONPATH='.'
python -u eval/run_live_eval.py --strict
# faster: --skip-routing  and/or  --skip-policy  and/or  --skip-vendors
```

Report: [`reports/live_eval_report.md`](../reports/live_eval_report.md).

Measured locally: routing **mock 100% / LLM 100%**; live field accuracy depends on fetch/extract quality (JS trust centres are hard).

## Key files

| Path | Role |
|------|------|
| [`assessor/router.py`](../assessor/router.py) | Router agent + offline mock |
| [`assessor/graders.py`](../assessor/graders.py) | Relevance + groundedness graders |
| [`assessor/policy_rag.py`](../assessor/policy_rag.py) | Widen / strict-regen / abstain loop |
| [`data/routing_gold.json`](../data/routing_gold.json) | 30 routing questions |
| [`eval/run_routing_eval.py`](../eval/run_routing_eval.py) | Mock vs LLM scorecard |
| [`tests/test_graders_m3.py`](../tests/test_graders_m3.py) | Awkward routes + hallucination abstain |
