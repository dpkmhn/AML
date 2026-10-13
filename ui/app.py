"""The analyst UI: a prioritised alert queue and a case page. It talks only to the API.

    uv run streamlit run ui/app.py        (API_URL defaults to http://localhost:8000)

The page is picked by query parameters: none is the queue, ?case=CASE-0001 is a case, and
?case=CASE-0001&view=audit is its audit trail.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
import pandas as pd
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
ROUTES = ["close", "escalate", "needs_info"]
LABELS = {"close": "Close", "escalate": "Escalate", "needs_info": "Needs more info"}

st.set_page_config(page_title="AML Triage Copilot", layout="wide")


def api(method: str, path: str, **kw: Any) -> httpx.Response:
    # POST /cases runs the graph to the review: allow it time
    return httpx.request(method, f"{API_URL}{path}", timeout=180, **kw)


def plain(text: str) -> str:
    """Text safe for st.markdown: no markdown or LaTeX from the data."""
    return re.sub(r"([\\`*_{}\[\]<>()#+\-.!|$~:])", r"\\\1", text)


def show_error(r: httpx.Response) -> None:
    try:
        detail = r.json().get("detail")
    except ValueError:
        detail = r.text
    if isinstance(detail, list):
        detail = "; ".join(d.get("msg", str(d)) for d in detail)
    st.error(f"{r.status_code}: {detail}")


def route_banner(route: str, text: str) -> None:
    {"escalate": st.error, "needs_info": st.warning, "close": st.success}[route](text)


# --- queue ---

def queue_page() -> None:
    st.title("Alert queue")
    st.caption("Alerts the copilot recommends escalating come first. Every final call is yours.")
    status = st.segmented_control("Status", ["open", "in_review", "closed", "all"],
                                  default="open")
    params = {} if status in (None, "all") else {"status": status}
    r = api("GET", "/alerts", params=params)
    if r.status_code != 200:
        show_error(r)
        return
    rows = r.json()
    if not rows:
        st.info("No alerts.")
        return
    df = pd.DataFrame(rows)
    df["recommended"] = df["recommended_route"].map(LABELS).fillna("")
    df["final"] = df["final_route"].map(LABELS).fillna("")
    df["window"] = df["window_start"] + " to " + df["window_end"]
    shown = df[["alert_id", "customer_name", "rule_id", "window", "status", "case_id",
                "recommended", "final"]]
    st.caption(f"{len(df)} alerts. Select a row, then open its case.")
    event = st.dataframe(shown, hide_index=True, use_container_width=True,
                         on_select="rerun", selection_mode="single-row",
                         column_config={"customer_name": "customer", "rule_id": "rule",
                                        "case_id": "case"})
    picked = event.selection.rows
    if not picked:
        return
    alert = df.iloc[picked[0]]
    label = "Open case" if alert["case_id"] else "Run the copilot and open the case"
    if st.button(f"{label}: {alert['alert_id']}", type="primary"):
        with st.spinner("Gathering the investigation pack (10 to 30 seconds)..."):
            r = api("POST", "/cases", json={"alert_id": alert["alert_id"]})
        if r.status_code != 200:
            show_error(r)
            return
        st.query_params.update(case=r.json()["case_id"])
        st.rerun()


# --- case ---

def highlight_quotes(notes: str, quotes: list[str]) -> str:
    """KYC notes as markdown with each quote the copilot relied on highlighted."""
    out, spans = plain(notes), []
    for q in quotes:
        i = notes.casefold().find(q.strip().strip("\"'").casefold())
        if i >= 0:
            spans.append((i, i + len(q.strip().strip("\"'"))))
    if not spans:
        return out
    spans.sort()
    parts, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue
        parts += [plain(notes[pos:a]), f":orange-background[{plain(notes[a:b])}]"]
        pos = b
    return "".join(parts) + plain(notes[pos:])


def header(pack: dict[str, Any]) -> None:
    c, a = pack["customer"], pack["alert"]
    st.title(f"{pack['case_id']}: {c['full_name']}")
    cols = st.columns(3)
    cols[0].metric("Segment", c["segment"])
    cols[1].metric("Risk rating", c["risk_rating"] + (" (PEP)" if c["is_pep"] else ""))
    cols[2].metric("Alert rule", a["rule_id"])
    st.markdown(f"Alert {a['alert_id']} · window {a['window_start']} to {a['window_end']} · "
                f"declared income AED {c['declared_monthly_income_aed']:,.0f}/month")
    st.caption(f"{c['customer_id']} · {plain(c['occupation'])} · expected activity: "
               f"{plain(c['expected_activity'])}")


def recommendation(pack: dict[str, Any]) -> None:
    route, assessment = pack["route"], pack.get("assessment") or {}
    confidence = assessment.get("confidence")
    text = (f"**Recommended: {LABELS[route['route']]}** · rules {', '.join(route['rule_ids'])}"
            + (f" · model confidence {confidence:.2f}" if confidence is not None else ""))
    route_banner(route["route"], text)
    for reason in route["reasons"]:
        st.markdown(f"- {plain(reason)}")
    if pack.get("assessment_errors"):
        st.warning("Post-checks still failing after the retry: "
                   + "; ".join(pack["assessment_errors"]))


def findings(pack: dict[str, Any], txns: dict[str, dict[str, Any]]) -> None:
    st.subheader("Typology findings")
    explained = set(pack["route"]["explained_typologies"])
    fired = [f for f in pack["findings"] if f["score"] > 0]
    if not fired:
        st.caption("No typology scored above zero.")
    for f in sorted(fired, key=lambda f: -f["score"]):
        tag = " · explained" if f["typology"] in explained else ""
        st.progress(f["score"], text=f"{f['typology']} {f['score']:.2f}{tag}")
        with st.expander(f"{plain(f['rule_explanation'])} "
                         f"({len(f['evidence_txn_ids'])} transactions)"):
            rows = [txns[i] for i in f["evidence_txn_ids"] if i in txns]
            if rows:
                st.dataframe(pd.DataFrame(rows)[["txn_id", "ts", "amount_aed", "direction",
                                                 "channel", "counterparty_name",
                                                 "counterparty_country", "reference"]],
                             hide_index=True, use_container_width=True)


def explanations(pack: dict[str, Any]) -> None:
    a = pack.get("assessment")
    if not a:
        return
    st.subheader("Activity")
    st.markdown(plain(a["activity_summary"]))
    for concern in a["concerns"]:
        st.markdown(f"- {plain(concern)}")

    st.subheader("Benign explanations")
    quotes = [b["kyc_quote"] for b in a["benign_explanations"] if b.get("kyc_quote")]
    if not a["benign_explanations"]:
        st.caption("None offered.")
    for b in a["benign_explanations"]:
        line = f"**{b['typology']}**: {plain(b['explanation'])}"
        if b.get("kyc_quote"):
            line += f"  \nKYC quote: :orange-background[{plain(b['kyc_quote'])}]"
        if b["evidence_txn_ids"]:
            line += f"  \nTransactions: {', '.join(b['evidence_txn_ids'])}"
        st.markdown(line)
    with st.expander("KYC notes, with the quoted words highlighted", expanded=bool(quotes)):
        st.markdown(highlight_quotes(pack["customer"]["kyc_notes"] or "(none)", quotes))

    st.subheader("Missing information")
    if not a["missing_information"]:
        st.caption("None.")
    for m in a["missing_information"]:
        flag = " (would change the decision)" if m["changes_decision"] else ""
        st.markdown(f"- {plain(m['item'])}{flag}")


def guidance(pack: dict[str, Any], content: dict[str, str]) -> None:
    st.subheader("Guidance")
    for g in sorted(pack["guidance"], key=lambda g: not g["cited"]):
        mark = "cited · " if g["cited"] else ""
        with st.expander(f"{mark}{g['chunk_id']}: {plain(g['section'])}"):
            st.markdown(plain(content.get(g["chunk_id"], "")))


def flagged(pack: dict[str, Any]) -> None:
    if not pack["flagged_references"]:
        return
    st.subheader("Flagged payment references")
    for f in pack["flagged_references"]:
        st.warning(f"{f['txn_id']}: {f['note']}")
        st.code(f["reference"] or "", language=None)  # customer-written: shown, never rendered


def decision_form(case: dict[str, Any]) -> None:
    st.subheader("Your decision")
    recommended = case["recommended_route"]
    key = case["case_id"]
    route = st.radio("Route", ROUTES, index=ROUTES.index(recommended), horizontal=True,
                     format_func=lambda r: LABELS[r] + (" (recommended)" if r == recommended
                                                        else ""), key=f"route-{key}")
    reviewer = st.text_input("Reviewer", key=f"reviewer-{key}")
    overriding = route != recommended
    reason = st.text_area("Reason" + (" (required: you are overriding the recommendation)"
                                      if overriding else " (optional)"), key=f"reason-{key}")
    blocked = not reviewer.strip() or (overriding and not reason.strip())
    if overriding and not reason.strip():
        st.caption("Give a reason to override the recommendation.")
    if st.button("Submit decision", type="primary", disabled=blocked):
        with st.spinner("Writing the narrative..."):
            r = api("POST", f"/cases/{key}/review",
                    json={"reviewer": reviewer.strip(), "final_route": route,
                          "override_reason": reason.strip() or None})
        if r.status_code != 200:
            show_error(r)
            return
        st.rerun()


def decided(case: dict[str, Any]) -> None:
    d = case["decision"] or {}
    st.subheader("Decision")
    route_banner(d.get("final_route", "close"),
                 f"**Final: {LABELS.get(d.get('final_route'), '?')}** by "
                 f"{plain(d.get('reviewer') or '?')} at {case['decided_at']}")
    if d.get("override_reason"):
        st.markdown(f"Override reason: {plain(d['override_reason'])}")
    st.subheader("Narrative")
    st.markdown(plain(case["narrative"] or "").replace("\n", "  \n"))
    if case["narrative_errors"]:
        st.warning("Narrative checks still failing: " + "; ".join(case["narrative_errors"]))


def case_page(case_id: str) -> None:
    nav = st.columns([2, 2, 5])
    if nav[0].button("Back to the queue"):
        st.query_params.clear()
        st.rerun()
    if nav[1].button("Audit trail"):
        st.query_params.update(case=case_id, view="audit")
        st.rerun()
    r = api("GET", f"/cases/{case_id}")
    if r.status_code != 200:
        show_error(r)
        return
    case = r.json()
    pack = case["pack"]
    if pack is None:
        st.warning(f"{case_id} did not reach the review step; open it again from the queue.")
        return
    txns = {t["txn_id"]: t for t in case["evidence_txns"]}
    header(pack)
    recommendation(pack)
    findings(pack, txns)
    explanations(pack)
    guidance(pack, case["guidance_content"])
    flagged(pack)
    if case["status"] == "awaiting_review":
        decision_form(case)
    else:
        decided(case)


def audit_page(case_id: str) -> None:
    if st.button("Back to the case"):
        st.query_params.update(case=case_id, view="case")
        st.rerun()
    st.title(f"{case_id}: audit trail")
    r = api("GET", f"/cases/{case_id}/audit")
    if r.status_code != 200:
        show_error(r)
        return
    rows = r.json()
    if not rows:
        st.info("No audit rows.")
        return
    df = pd.DataFrame(rows)
    st.caption(f"{len(df)} steps · {int(df['tokens_in'].fillna(0).sum())} tokens in · "
               f"{int(df['tokens_out'].fillna(0).sum())} tokens out")
    st.dataframe(df[["id", "created_at", "step", "model", "prompt_version", "tokens_in",
                     "tokens_out", "latency_ms"]], hide_index=True, use_container_width=True)
    for row in rows:
        with st.expander(f"{row['id']} {row['step']}"):
            st.json(row["output"], expanded=False)


case_id = st.query_params.get("case")
if case_id and st.query_params.get("view") == "audit":
    audit_page(case_id)
elif case_id:
    case_page(case_id)
else:
    queue_page()
