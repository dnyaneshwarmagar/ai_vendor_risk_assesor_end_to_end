"""
app/ui.py — Streamlit front end for reviewers (Milestone 5).

Run (with API up):
  uvicorn app.api:app --port 8000
  streamlit run app/ui.py

Calls the API so assessments queue, pause at the human gate, and decisions survive restart.
ACL groups come from the chosen identity (X-User-Id) — not a free-form multiselect.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import streamlit as st

from app import settings

st.set_page_config(page_title="Vendor Risk Assessor — Nimbu Mart", layout="wide")
st.title("AI Vendor Risk Assessor")
st.caption("Nimbu Mart · queued assessments · durable human gate · ACL from identity")

API = settings.API_BASE.rstrip("/")


def _headers(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id, "Content-Type": "application/json"}


def _trace_tree(events: list[dict]) -> dict[str, Any]:
    root: dict[str, Any] = {"name": "assessment", "children": []}
    by_stage: dict[str, dict] = {}
    for e in events or []:
        stage = e.get("stage") or "event"
        node = by_stage.setdefault(stage, {"name": stage, "children": [], "events": []})
        node["events"].append({k: v for k, v in e.items() if k != "stage"})
    order = ["engine", "guard_input", "route", "vendor_research", "match", "questionnaire",
             "human_gate", "report", "approval", "policy_qa"]
    for name in order:
        if name in by_stage:
            root["children"].append(by_stage.pop(name))
    root["children"].extend(by_stage.values())
    return root


with st.sidebar:
    st.header("Identity (ACL)")
    user_id = st.selectbox(
        "Signed-in user",
        options=list(settings.IDENTITY_MAP.keys()),
        index=list(settings.IDENTITY_MAP.keys()).index("reviewer"),
        help="Groups are derived on the server from X-User-Id — never sent by the client.",
    )
    st.write("Server groups:", ", ".join(settings.IDENTITY_MAP[user_id]))
    tier = st.selectbox("Highest data tier", ["T1", "T2", "T3"], index=2)
    users = st.number_input("Number of users", 1, 10000, 35)
    vendor = st.text_input("Vendor", "LedgerLens AI")
    domain = st.text_input("Official domain", "ledgerlens.example")
    st.divider()
    st.caption(f"API: {API}")

q = st.text_input("Question", "Can our support team use LedgerLens AI to summarise customer tickets?")

col_run, col_obs = st.columns([2, 1])
with col_run:
    run_clicked = st.button("Assess (queued)", type="primary")
with col_obs:
    show_obs = st.button("Refresh observability")

if "job_id" not in st.session_state:
    st.session_state.job_id = None
if "job" not in st.session_state:
    st.session_state.job = None

if run_clicked:
    try:
        r = httpx.post(
            f"{API}/assess",
            headers=_headers(user_id),
            json={
                "question": q,
                "vendor": vendor,
                "official_domain": domain or None,
                "tier": tier,
                "users": int(users),
                "requested_by": user_id,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        st.session_state.job_id = r.json()["run_id"]
        st.session_state.job = r.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not enqueue assessment: {exc}")

job_id = st.session_state.job_id
if job_id:
    progress = st.empty()
    status_box = st.empty()
    # Poll until awaiting_approval or completed/failed
    job = None
    for _ in range(120):
        try:
            resp = httpx.get(f"{API}/jobs/{job_id}", headers=_headers(user_id), timeout=30.0)
            resp.raise_for_status()
            job = resp.json()
            st.session_state.job = job
        except Exception as exc:  # noqa: BLE001
            status_box.warning(f"Polling… ({exc})")
            time.sleep(1.0)
            continue
        status = job.get("status")
        timings = job.get("stage_timings") or {}
        stages = " → ".join(f"{k} ({v}ms)" for k, v in timings.items()) or "starting…"
        progress.info(f"**{status}** · {stages}")
        if status in ("awaiting_approval", "completed", "failed"):
            break
        time.sleep(0.8)

    job = st.session_state.job or job
    if not job:
        st.stop()

    left, right = st.columns([3, 2])
    with left:
        overall = job.get("overall") or (job.get("report") or {}).get("overall")
        colour = {"BLOCKED": "red", "CONDITIONAL": "orange", "READY_FOR_APPROVAL": "green"}.get(overall or "", "gray")
        st.markdown(f"### :{colour}[{overall or job.get('status')}]")
        rep = job.get("report") or {}
        if isinstance(rep, dict) and rep.get("overall_reason"):
            st.write(rep["overall_reason"])
        results = rep.get("results") or []
        if results:
            rows = [
                {
                    "Requirement": r.get("title"),
                    "Clause": r.get("clause"),
                    "Verdict": r.get("verdict"),
                    "Severity": r.get("severity"),
                    "Reason": r.get("reason"),
                    "Evidence": ", ".join((r.get("evidence_urls") or [])[:2]),
                }
                for r in results
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
        oqs = rep.get("open_questions") or []
        if oqs:
            st.subheader("Questions for the vendor")
            for i, oq in enumerate(oqs, 1):
                st.markdown(f"**{i}. {oq.get('id')}** — {oq.get('question')}")
            st.download_button(
                "Download vendor questions",
                data="\n\n".join(f"{i}. {oq.get('question')}" for i, oq in enumerate(oqs, 1)),
                file_name=f"{job_id}-vendor-questions.txt",
            )

        # Approve / Reject — hidden Approve when BLOCKED
        if job.get("status") == "awaiting_approval":
            st.subheader("Human decision")
            with st.form("approve_form"):
                approver = st.text_input("Reviewer name", value=user_id)
                comment = st.text_area("Comment", "")
                c1, c2 = st.columns(2)
                do_reject = c1.form_submit_button("Reject")
                do_approve = None
                if overall != "BLOCKED":
                    do_approve = c2.form_submit_button("Approve", type="primary")
                else:
                    c2.warning("BLOCKED — Approve is not offered.")
            decision = None
            if do_reject:
                decision = "reject"
            elif do_approve:
                decision = "approve"
            if decision:
                try:
                    ar = httpx.post(
                        f"{API}/approve/{job_id}",
                        headers=_headers(user_id),
                        json={"decision": decision, "approver": approver, "comment": comment},
                        timeout=120.0,
                    )
                    if ar.status_code == 409:
                        st.error(ar.json().get("detail") or ar.text)
                    else:
                        ar.raise_for_status()
                        st.success(f"Decision recorded: {ar.json()}")
                        st.session_state.job = httpx.get(
                            f"{API}/jobs/{job_id}", headers=_headers(user_id), timeout=30.0
                        ).json()
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Approve failed: {exc}")
        elif job.get("status") == "completed" and isinstance(rep, dict):
            appr = rep.get("approval") or job.get("approval") or {}
            st.info(f"Decision: **{appr.get('status')}** by {appr.get('decided_by')} — {appr.get('comment') or ''}")

    with right:
        st.subheader("Trace tree")
        tree = _trace_tree(job.get("trace") or [])
        st.json(tree)
        if job.get("stage_timings"):
            st.subheader("Stage timings (ms)")
            st.json(job["stage_timings"])
        st.caption(f"Run `{job_id}` · cost ${job.get('cost_usd') or 0:.4f} · {job.get('duration_s') or 0}s")

        st.subheader("Vendor history")
        try:
            hist = httpx.get(f"{API}/vendors/{vendor}/history", headers=_headers(user_id), timeout=30.0).json()
            for h in hist.get("history") or []:
                mark = " ✎ changed" if h.get("changed_since_previous") else ""
                st.write(f"- `{h.get('run_id')}` · {h.get('overall')} · {h.get('status')}{mark}")
        except Exception:
            st.caption("History unavailable")

if show_obs or st.checkbox("Show observability table", value=False):
    st.subheader("Last 20 runs — latency & cost")
    try:
        obs = httpx.get(f"{API}/observability", headers=_headers(user_id), timeout=30.0).json()
        st.write(
            f"p50 duration **{obs['duration_s']['p50']}s** · p95 **{obs['duration_s']['p95']}s** · "
            f"p50 cost **${obs['cost_usd']['p50']}** · p95 **${obs['cost_usd']['p95']}**"
        )
        st.dataframe(obs.get("runs") or [], use_container_width=True, hide_index=True)
        if obs.get("stages"):
            st.json(obs["stages"])
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Observability unavailable: {exc}")
