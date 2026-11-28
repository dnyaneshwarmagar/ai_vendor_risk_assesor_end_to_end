# Milestone 4 — Security: attack it, then defend in layers

Deep Search Modules 08 / 11 · Lab 9 · Production RAG Module 11 · Lab 11

## Goal

Untrusted content — web pages, chat exports, the user’s own question — must **never** change a verdict. Every attack has a named catch point.

## Defence in depth

| Layer | Where | Catch point |
|-------|--------|-------------|
| Intent check | [`assessor/guardrails.py`](../assessor/guardrails.py) `check_intent` | `intent_check` |
| Identity gate | [`assessor/vendor_research.py`](../assessor/vendor_research.py) | `identity_gate` |
| Regex tripwire | [`assessor/security.py`](../assessor/security.py) | `quarantine` / `policy_injection` |
| Classifier (Lab 9) | `inspect_untrusted_text` heuristics (+ small LLM when live) | `quarantine` |
| Rumour / forum drop | evidence filter before merge | `dropped` |
| Spotlighting | extractor prompt wraps page text | (containment) |
| Output policy | `enforce_output_policy` | `output_guardrail` |

Config: `VRA_IDENTITY_GATE=1` (default), `VRA_INJECTION_CLASSIFIER=1` (default).

## Red-team suite

```bash
python -m pytest tests/test_red_team.py -q
```

15 attacks in [`tests/test_red_team.py`](../tests/test_red_team.py); each asserts its catch point. Also measures **false positives = 0** on clean corpus pages.

## Identity-gate ablation (“screenshot”)

```bash
python scripts/m4_identity_ablation.py
```

Side-by-side output (also written to [`reports/m4_identity_ablation.md`](../reports/m4_identity_ablation.md)):

```
┌──────────────────────────────────────────────────────────────────────────┐
│  IDENTITY GATE ON                          IDENTITY GATE OFF             │
├──────────────────────────────────────────────────────────────────────────┤
│  lookalike URL: REJECTED ✓                 lookalike URL: ACCEPTED ✗     │
│  UK ISO in cert fact: no ✓                 UK ISO in conflicts: YES ✗    │
└──────────────────────────────────────────────────────────────────────────┘
```

With the gate off, `https://ledgerlens-uk.example/about-us` injects **ISO 27001 / UK-27001-0822** into LedgerLens’s `security_certifications.conflicts` (official trust centre may still win the primary value). That is the proof the gate is load-bearing.

## Module 11 privacy checklist

| Check | Status |
|-------|--------|
| Vendor fact schema holds no personal data of people | Yes — fields are company/security facts only ([`schemas.py`](../assessor/schemas.py)) |
| Questionnaire email names a **role**, not a person | Yes — `Nimbu Mart Information Security` ([`questionnaire.py`](../assessor/questionnaire.py) `as_email`) |
| Nothing from a vendor’s employees is stored | Yes — no employee PII fields; input emails/phones redacted in `redact_input` before models/logs |
| Policy chat exports stay untrusted / injection-flagged | Yes — `team_chat_vendor_notes_untrusted.md` flagged at ingest and filtered from retrieval |

## Done when

- [x] 15/15 attacks caught with catch point asserted
- [x] Classifier FP rate 0 on clean pages
- [x] Ablation write-up shows UK ISO leak
- [x] Privacy checklist applied
- [x] Offline gold-set **safety = 100%**, **guess_rate = 0** (`python eval/run_eval.py --strict`)
