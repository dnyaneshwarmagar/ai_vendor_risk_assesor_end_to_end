# Milestone 1 — Production-grade policy library

## What changed

- Copied course [`rag_core/`](../rag_core/) into the project.
- [`assessor/policy_rag.py`](../assessor/policy_rag.py) now uses **hybrid BM25 + vectors (RRF)** and a **cross-encoder reranker**, with ACL / archived / draft / untrusted / injection filters **before** ranking.
- Policy answers use **local Ollama** for grounded generation (`LLM_PROVIDER=ollama`); extractive mode remains the fallback (mock, grader refusal, or Ollama errors).
- Fixed gold case **`pq-who-approves`** (AI-5.1 over SEC-7.1) via hybrid + rerank + heading overlap boost.
- Added three policies: incident-response runbook, 2027 draft (`status: draft`), business-continuity policy — plus three gold questions.

## Local setup

```bash
ollama pull qwen2.5:7b
# .env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
SEARCH_PROVIDER=offline
EMBEDDER=wordllama   # optional; default
```

## Verify

```bash
python -m pytest tests -q
python eval/run_eval.py
```

Expect: all assessment metrics at threshold; **policy_qa soft and hard at 100%**, including `pq-who-approves`.
