import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import math
import streamlit as st
from root_cause_engine import normalize_events, rank_causes
from incident_modules import build_dependency_graph, retrieve_similar_capsules, save_capsule, draft_recovery, next_diagnostic_test, capsule_payload, compare_candidate_evidence
from live_integrations import prometheus_range_events, validate_event_frame, IntegrationError

from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

def build_readable_pdf(title, sections):
    """Create a readable multi-page PDF from (heading, body) sections."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm, title=str(title)
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RootCauseTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=20, leading=25, textColor=colors.HexColor("#183153"),
        alignment=TA_LEFT, spaceAfter=10
    )
    heading_style = ParagraphStyle(
        "RootCauseHeading", parent=styles["Heading2"], fontSize=12,
        leading=16, textColor=colors.HexColor("#24558a"),
        spaceBefore=10, spaceAfter=5, keepWithNext=True
    )
    body_style = ParagraphStyle(
        "RootCauseBody", parent=styles["BodyText"], fontSize=9,
        leading=13, textColor=colors.HexColor("#263445"), spaceAfter=5,
        splitLongWords=True
    )
    story = [
        Paragraph(escape(str(title)), title_style),
        Paragraph("ROOTCAUSE AI | Evidence-linked incident investigation", body_style),
        Spacer(1, 5*mm)
    ]
    for heading, body in sections:
        story.append(Paragraph(escape(str(heading)), heading_style))
        lines = body if isinstance(body, (list, tuple)) else str(body).splitlines()
        if not lines:
            lines = ["Not available."]
        for line in lines:
            line = str(line).strip()
            if not line:
                story.append(Spacer(1, 2*mm))
            else:
                story.append(Paragraph(escape(line), body_style))

    def draw_footer(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d6deea"))
        canvas.line(18*mm, 13*mm, A4[0]-18*mm, 13*mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#65758b"))
        canvas.drawString(18*mm, 8*mm, "Heuristic analysis only — verify before confirming a cause.")
        canvas.drawRightString(A4[0]-18*mm, 8*mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


st.set_page_config(page_title="RootCause AI | Incident Intelligence", page_icon="🔎", layout="wide", initial_sidebar_state="expanded")

# Use the independently testable report builder for both PDF downloads.
from reporting import build_readable_pdf

# Professional dark operations-console styling
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
html { scroll-behavior: smooth; }
.stApp { background: radial-gradient(ellipse at 10% 0%, rgba(43,78,130,.20), transparent 36%), #0b1020; color: #e8edf7; }
.block-container { padding-top: 1.4rem; padding-bottom: 2.5rem; max-width: 1500px; }
h1, h2, h3 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -.025em; }
[data-testid="stSidebar"] { background: #0e1528; border-right: 1px solid #26324b; }
[data-testid="stMetric"] { background: linear-gradient(145deg,#151f35,#10182a); border: 1px solid #283753; padding: 16px 18px; border-radius: 16px; }
[data-testid="stMetricLabel"] { color: #9eacc6 !important; font-size: .82rem !important; }
[data-testid="stMetricValue"] { color: #f4f7ff !important; font-family: 'Space Grotesk', sans-serif; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-color: #263550 !important; background: rgba(17,26,45,.72); border-radius: 16px; }
.stTabs [data-baseweb="tab-list"] { gap: 8px; border-bottom: 1px solid #263550; }
.stTabs [data-baseweb="tab"] { background: transparent; border-radius: 10px 10px 0 0; padding: 12px 18px; color: #9eacc6; }
.stTabs [aria-selected="true"] { color: #8bb7ff !important; border-bottom-color: #5b9aff !important; }
.stButton > button, .stDownloadButton > button { border-radius: 10px; border: 1px solid #38517b; background: #172743; color: #eaf2ff; font-weight: 600; }
.stButton > button:hover, .stDownloadButton > button:hover { border-color: #79aaff; background: #20385e; color: white; }
div[data-testid="stAlert"] { border-radius: 12px; }
.small-muted { color: #91a0bc; font-size: .88rem; }
.hero { padding: 24px 26px; border: 1px solid #2b4164; border-radius: 20px; background: linear-gradient(120deg,rgba(32,57,96,.72),rgba(16,25,44,.88)); margin-bottom: 18px; }
.hero-kicker { color: #8bb7ff; text-transform: uppercase; font-size: .75rem; font-weight: 700; letter-spacing: .14em; }
.hero-title { font-family: 'Space Grotesk',sans-serif; font-size: 2.35rem; font-weight: 700; line-height: 1.1; margin: 6px 0 8px 0; color: #f5f8ff; }
.hero-sub { color: #aab8d1; font-size: 1rem; }
.pill { display:inline-block; padding:4px 9px; border-radius:999px; font-size:.75rem; font-weight:700; background:#172d49; color:#9bc4ff; border:1px solid #31527e; }
.section-label { color:#8bb7ff; text-transform:uppercase; letter-spacing:.12em; font-size:.75rem; font-weight:700; margin-bottom:4px; }
.hero-cta { display:inline-block; margin-top:16px; padding:10px 15px; border:1px solid #5c8dcb; border-radius:10px; background:#193457; color:#f0f6ff !important; text-decoration:none; font-weight:700; transition:background .18s ease,border-color .18s ease; }
.hero-cta:hover { background:#244875; border-color:#9bc4ff; }
</style>
""", unsafe_allow_html=True)

DEMO_EVENTS = [
    {"time":"13:55:00","service":"inventory","type":"config_change","severity":"warning","message":"Connection pool size changed from 50 to 10","source":"configuration","event_id":"EV-001"},
    {"time":"14:00:00","service":"inventory","type":"metric","severity":"warning","message":"Connection wait time increased to 820 ms","source":"metrics","event_id":"EV-002"},
    {"time":"14:02:00","service":"checkout","type":"metric","severity":"critical","message":"Checkout p95 latency increased to 4.8 seconds","source":"metrics","event_id":"EV-003"},
    {"time":"14:03:00","service":"checkout","type":"log","severity":"critical","message":"Timeout while waiting for inventory response","source":"logs","event_id":"EV-004"},
    {"time":"14:05:00","service":"inventory","type":"log","severity":"critical","message":"Connection pool exhausted; request queue growing","source":"logs","event_id":"EV-005"},
    {"time":"14:08:00","service":"payments","type":"trace","severity":"warning","message":"Checkout trace shows delay in inventory dependency span","source":"traces","event_id":"EV-006"},
    {"time":"14:40:00","service":"payments","type":"deployment","severity":"info","message":"Payments service restarted; checkout latency recovered","source":"deployment","event_id":"EV-007"},
    {"time":"13:50:00","service":"catalog","type":"config_change","severity":"info","message":"Cache TTL changed from 60 to 90 seconds","source":"configuration","event_id":"EV-008"},
    {"time":"14:01:00","service":"catalog","type":"metric","severity":"info","message":"Catalog request rate remains within normal range","source":"metrics","event_id":"EV-009"},
]

with st.sidebar:
    st.markdown("## 🔎 RootCause AI")
    st.markdown('<span class="pill">INCIDENT INTELLIGENCE</span>', unsafe_allow_html=True)
    st.write("")
    st.markdown("### Investigation")
    mode = st.radio("Data source", ["Built-in demo scenario", "Upload your own CSV", "Connect Prometheus metrics"])
    st.divider()
    st.markdown("**CSV schema**")
    st.code("time, service, type, severity,\nmessage, source, event_id", language="text")
    st.caption("Use approved, redacted data only. Never upload credentials, tokens, or personal data.")
    st.divider()
    st.markdown('<div class="small-muted">Prototype build v0.3<br>Evidence-first · Read-only analysis</div>', unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="hero-kicker">AIOps / Incident investigation</div>
  <div class="hero-title">Every incident leaves evidence.<br>Find the strongest lead.</div>
  <div class="hero-sub">Correlate telemetry and change events to surface likely causes with inspectable evidence.</div>
  <a class="hero-cta" href="#investigation-workspace">Investigate incident ↓</a>
</div>
""", unsafe_allow_html=True)
st.warning("Heuristic ranking only: scores prioritize candidates; they are not calibrated probabilities or proof of causation. Verify every conclusion against source evidence.")

if mode == "Built-in demo scenario":
    raw = pd.DataFrame(DEMO_EVENTS)
    demo = True
    data_source_label = "Built-in synthetic demo"
elif mode == "Upload your own CSV":
    upload = st.file_uploader("Upload incident events (.csv)", type=["csv"], help="Recommended columns: time, service, type, severity, message, source, event_id")
    if upload is None:
        st.info("Upload a CSV to start an investigation. You can switch to the built-in demo in the sidebar.")
        st.stop()
    try:
        raw = validate_event_frame(pd.read_csv(upload))
        demo = False
        data_source_label = "Uploaded CSV"
    except Exception as exc:
        st.error(f"Could not load this CSV: {exc}")
        st.stop()
else:
    st.subheader("Read-only Prometheus connector")
    st.caption("Queries numeric time-series data only. This does not automatically ingest logs or traces. Use CSV for those sources until you configure a separate adapter.")
    with st.form("prometheus_connection_form"):
        prom_url = st.text_input("Prometheus base URL", placeholder="http://localhost:9090", help="For a hosted app, localhost means the hosted container, not your laptop.")
        prom_query = st.text_input("PromQL query", value='up', help="Example: up or rate(http_requests_total[5m])")
        prom_minutes = st.slider("Lookback window (minutes)", min_value=5, max_value=240, value=30, step=5)
        prom_step = st.select_slider("Sample interval", options=[15, 30, 60, 120, 300], value=60, format_func=lambda v: f"{v} seconds")
        prom_submit = st.form_submit_button("Fetch metrics and investigate")
    if not prom_submit:
        st.info("Enter a reachable Prometheus endpoint and query, then click Fetch metrics and investigate.")
        st.stop()
    try:
        raw = prometheus_range_events(prom_url, prom_query, prom_minutes, prom_step)
        demo = False
        data_source_label = "Prometheus API"
        st.success(f"Fetched {len(raw)} metric samples from Prometheus. These are observations, not automatically classified anomalies.")
    except IntegrationError as exc:
        st.error(str(exc))
        st.stop()
    except Exception as exc:
        st.error(f"Unexpected connector error ({type(exc).__name__}). Check configuration and logs; no changes were made to the monitored system.")
        st.stop()

events = normalize_events(raw)
analysis = rank_causes(raw)
display_events = events.drop(columns=["_time"], errors="ignore")
critical_count = int(display_events["severity"].str.lower().isin(["critical", "error", "high"]).sum())
services_count = int(display_events["service"].replace("", pd.NA).nunique())
change_count = int((display_events["type"].str.contains(r"config|change|deploy|release|restart|rollback", case=False, na=False) |
                    display_events["message"].str.contains(r"config|change|deploy|release|restart|rollback", case=False, na=False)).sum())

st.markdown('<div id="investigation-workspace"></div><div class="section-label">Live investigation snapshot</div>', unsafe_allow_html=True)
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Events ingested", len(display_events))
m2.metric("Services observed", services_count)
m3.metric("High-severity events", critical_count)
m4.metric("Change events", change_count)
m5.metric("Investigation", "Needs evidence" if analysis["unknown"] else "Candidate found")

overview_left, overview_right = st.columns([1.6, 1])
with overview_left:
    st.subheader("Investigation overview")
    st.write("The system looks for changes that precede symptoms, checks same-service and cross-service evidence, then ranks candidate explanations.")
    st.markdown('<span class="pill">READ-ONLY</span> &nbsp; <span class="pill">EVIDENCE-LINKED</span> &nbsp; <span class="pill">HYPOTHESIS-BASED</span>', unsafe_allow_html=True)
with overview_right:
    if demo:
        st.markdown("""
        <div style="border:1px solid #34517a;background:rgba(24,43,70,.75);padding:17px;border-radius:15px;">
        <div class="section-label">Demo scenario</div>
        <b>Checkout latency spike</b><br>
        <span class="small-muted">Incident starts at 14:02 · Recovery follows payments restart at 14:40</span><br><br>
        Leading candidate: inventory connection-pool reduction at 13:55.
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="border:1px solid #34517a;background:rgba(24,43,70,.75);padding:17px;border-radius:15px;">
        <div class="section-label">{data_source_label}</div>
        <b>Custom incident investigation</b><br>
        <span class="small-muted">Rankings depend on the quality and completeness of supplied event records.</span>
        </div>""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["🎯 Ranked causes", "🕒 Timeline", "🧾 Evidence", "📄 Report", "🧠 Incident memory", "🕸️ Dependency graph", "🧪 Diagnostics & recovery"])
with tab1:
    st.subheader("Candidate root causes")
    if analysis["unknown"]:
        st.info(analysis["message"])
    if not analysis["candidates"]:
        st.warning(analysis["message"])
    for idx, candidate in enumerate(analysis["candidates"], 1):
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"### #{idx} · {candidate['cause']}")
                st.markdown(f'<span class="pill">SERVICE: {candidate["service"].upper()}</span> &nbsp; <span class="small-muted">Event time: {candidate["event_time"]}</span>', unsafe_allow_html=True)
                st.write(candidate["status"])
                for reason in candidate["reasons"]:
                    st.markdown(f"- {reason}")
            with c2:
                st.metric("Ranking score", f"{candidate['score']*100:.0f}/100")
            ids = candidate["evidence_ids"]
            evidence = display_events[display_events["event_id"].astype(str).isin(ids)]
            if not evidence.empty:
                st.markdown("**Supporting evidence**")
                st.dataframe(evidence[["event_id","time","service","type","severity","message"]], use_container_width=True, hide_index=True)
    st.caption("Scores are heuristic prioritization indicators, not probabilities. Ranking does not prove causation.")

with tab2:
    st.subheader("Event sequence")
    timeline = events.sort_values("_time", na_position="last").drop(columns=["_time"], errors="ignore")
    severity_options = sorted(x for x in timeline["severity"].dropna().astype(str).unique() if x.strip())
    chosen_severities = st.multiselect("Filter by severity", severity_options, default=severity_options)
    if chosen_severities:
        timeline = timeline[timeline["severity"].astype(str).isin(chosen_severities)]
    else:
        timeline = timeline.iloc[0:0]
    if not timeline.empty:
        timeline_chart = timeline.copy()
        timeline_chart["event_order"] = range(1, len(timeline_chart)+1)
        fig = px.scatter(timeline_chart, x="event_order", y="service", color="severity",
                         hover_data=["time","type","message","event_id"],
                         title="Incident events by service")
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#dce6f7", xaxis_title="Event order", yaxis_title="Service",
            margin=dict(l=10,r=10,t=55,b=10), legend_title_text="Severity"
        )
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(timeline[["time","service","type","severity","message","event_id"]], use_container_width=True, hide_index=True)

with tab3:
    st.subheader("Evidence explorer")
    search = st.text_input("Search by event, service, severity, or keyword", placeholder="e.g. inventory, timeout, EV-004")
    view = display_events.copy()
    if search:
        mask = view.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False, regex=False)).any(axis=1)
        view = view[mask]
    st.caption(f"Showing {len(view)} of {len(display_events)} event records")
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.download_button("⬇ Download normalized evidence CSV", data=display_events.to_csv(index=False).encode("utf-8"),
                       file_name="rootcause_evidence.csv", mime="text/csv")

with tab4:
    st.subheader("Post-incident report")
    if analysis["candidates"]:
        top = analysis["candidates"][0]
        evidence_comparison = compare_candidate_evidence(top, display_events)
        evidence_rows = display_events[display_events["event_id"].astype(str).isin(top["evidence_ids"])]
        evidence_lines = [
            f"- **{row['event_id']}** · {row['time']} · {row['service']} · {row['severity']}: {row['message']}"
            for _, row in evidence_rows.iterrows()
        ]
        evidence_text = "\n".join(evidence_lines) if evidence_lines else "No linked evidence records were available."
        confidence_note = (
            "The engine found a candidate above its heuristic threshold; independent verification is still required."
            if not analysis["unknown"] else
            "The engine considers the available evidence insufficient for a strong conclusion. Do not present this candidate as a confirmed root cause."
        )
        ranked_hypotheses = "\n".join(
            f"{i}. {item['cause']} ({item['service']}) — {item['score']*100:.0f}/100; {item['status']}"
            for i, item in enumerate(analysis["candidates"], 1)
        )
        contradictory_text = "\n".join(
            f"- {row['event_id']} · {row['time']} · {row['service']}: {row['message']}"
            for row in evidence_comparison["contradictory"]
        ) or "No explicit contradictory normal signal was found in the candidate service window."
        report = f"""# Incident investigation report

## Investigation status
{confidence_note}

## Leading candidate
{top['cause']}

- Service: {top['service']}
- Event time: {top['event_time']}
- Heuristic ranking score: {top['score']*100:.0f}/100 (not a probability)
- Status: {top['status']}

## Supporting reasoning
""" + "\n".join("- " + r for r in top["reasons"]) + "\n\n## Linked evidence\n" + evidence_text + "\n\n## Limitations\nThis is a heuristic hypothesis based only on supplied records. Temporal correlation and text matching do not prove causation. Verify timestamps, source telemetry, service dependencies, and the proposed change with the incident owner before treating this as a finding."
        report += "\n\n## Ranked hypotheses\n" + ranked_hypotheses
        report += "\n\n## Contradictory signals\n" + contradictory_text
        report += "\n\n## Missing information\n" + "\n".join(f"- {item}" for item in evidence_comparison["missing"])
    else:
        report = "# Incident investigation report\n\nThe available evidence is insufficient to rank a suitable candidate. No root cause has been established."
    st.markdown(report)
    pdf_sections = [
        ("Investigation status", confidence_note if analysis["candidates"] else "Insufficient evidence to rank a suitable candidate. No root cause has been established."),
    ]
    if analysis["candidates"]:
        pdf_sections.extend([
            ("Leading candidate", f"{top['cause']} | Service: {top['service']} | Event time: {top['event_time']}"),
            ("Ranking and verification", f"Heuristic ranking score: {top['score']*100:.0f}/100 (not a probability). Status: {top['status']}"),
            ("Supporting reasoning", top.get("reasons", []) or ["No explicit reasoning was returned."]),
            ("Ranked hypotheses", [
                f"#{i} {item['cause']} | {item['service']} | {item['score']*100:.0f}/100 | {item['status']}"
                for i, item in enumerate(analysis["candidates"], 1)
            ]),
            ("Linked evidence", [
                f"{row['event_id']} | {row['time']} | {row['service']} | {row['severity']} | {row['message']}"
                for _, row in evidence_rows.iterrows()
            ] or ["No linked evidence records were available."]),
            ("Contradictory signals", [
                f"{row['event_id']} | {row['time']} | {row['service']} | {row['message']}"
                for row in evidence_comparison["contradictory"]
            ] or ["No explicit contradictory normal signal was found in the candidate service window."]),
            ("Missing information", evidence_comparison["missing"]),
            ("Limitations", "This report is based on supplied records and deterministic heuristics. Temporal correlation and text matching do not prove causation. Verify timestamps, telemetry, service dependencies and change records with the incident owner."),
        ])
    else:
        pdf_sections.append(("Finding", "No root cause has been established from the available evidence. Collect initiating-change records and symptom telemetry."))
    report_pdf = build_readable_pdf("Incident Investigation Report", pdf_sections)
    st.download_button("⬇ Download readable incident report (PDF)", data=report_pdf,
                       file_name="rootcause_incident_report.pdf", mime="application/pdf")


with tab5:
    st.subheader("Module 1 · Incident Memory Capsules")
    st.write("Save an incident snapshot outside the failing application in a local SQLite database. Capsules preserve the current evidence, hypothesis status, diagnostic plan, proposed recovery, and outcome status.")
    similar = retrieve_similar_capsules(display_events)
    if similar:
        st.markdown("**Similar historical capsules**")
        st.dataframe(pd.DataFrame(similar)[["id","title","created_at","status","cause","similarity","outcomes"]], use_container_width=True, hide_index=True)
    else:
        st.info("No historical capsules found yet. Save this incident below to seed local memory.")
    if analysis["candidates"]:
        candidate_options = list(range(len(analysis["candidates"])))
        selected_candidate_index = st.selectbox("Candidate to record", candidate_options, format_func=lambda i: f"{analysis['candidates'][i]['service']} — {analysis['candidates'][i]['cause']}")
        capsule_candidate = analysis["candidates"][selected_candidate_index]
    else:
        capsule_candidate = None
    with st.form("capsule_form"):
        capsule_title = st.text_input("Incident title", value="Checkout latency investigation" if demo else "Uploaded incident investigation")
        capsule_status = st.selectbox("Cause verification status", ["suspected", "supported", "confirmed", "unknown"], help="Use confirmed only after independent verification by an incident owner.")
        capsule_outcome = st.text_area("Verified outcome / recovery result", placeholder="Leave as unverified if the incident owner has not confirmed it.")
        save_clicked = st.form_submit_button("Save incident memory capsule")
    if save_clicked:
        capsule_recovery = draft_recovery(analysis["candidates"], display_events, similar)
        capsule_diagnostic = next_diagnostic_test(analysis["candidates"], display_events)
        payload = capsule_payload(capsule_title, capsule_status, capsule_candidate, display_events, capsule_recovery, capsule_diagnostic)
        payload["outcome"] = capsule_outcome.strip() or "Unverified — update after incident owner review"
        save_capsule(payload["title"], payload["status"], payload["cause"], payload["summary"], payload["evidence_ids"], payload["diagnostic_tests"], payload["recovery_actions"], payload["outcome"])
        st.success("Capsule saved locally. It remains a record, not an independently verified finding.")
    st.caption("Storage is local to this project folder. Back up incident_memory.sqlite3 to preserve capsules; don't upload sensitive or unredacted telemetry.")

with tab6:
    st.subheader("Module 2 · Analysis-generated causal hypothesis graph")
    graph = build_dependency_graph(display_events, analysis.get("candidates", []))
    summary = graph.get("summary", {})
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Event nodes", summary.get("event_count", len(graph["nodes"])))
    g2.metric("Possible links", summary.get("edge_count", len(graph["edges"])))
    g3.metric("Change events", summary.get("change_count", 0))
    g4.metric("Abnormal events", summary.get("abnormal_event_count", 0))
    st.warning("This is an evidence-linked causal hypothesis graph generated from the selected incident data. Arrows show rule-inferred possible relationships, not confirmed causation.")
    if graph["nodes"]:
        node_df = pd.DataFrame(graph["nodes"])
        edge_df = pd.DataFrame(graph["edges"])
        # Stable deterministic layout: time flows left-to-right; services occupy lanes.
        parsed = pd.to_datetime(node_df["time"], errors="coerce", format="mixed")
        node_df["_parsed"] = parsed
        valid_times = parsed.dropna()
        base_time = valid_times.min() if not valid_times.empty else None
        service_names = list(dict.fromkeys(node_df["service"].fillna("unknown service").astype(str).tolist()))
        lane_y = {service: (len(service_names)-i-1) * 2.0 for i, service in enumerate(service_names)}
        positions = {}
        for i, node in node_df.iterrows():
            t = node["_parsed"]
            x = (t-base_time).total_seconds()/60 if base_time is not None and pd.notna(t) else float(i)
            # Separate same-time nodes slightly to avoid exact overlap.
            positions[str(node["id"])] = (x + (i % 3)*0.12, lane_y.get(str(node["service"]), 0) + ((i % 3)-1)*0.12)
        fig = go.Figure()
        # Draw directed edges behind nodes; labels and evidence rationale are available below.
        for edge in graph["edges"]:
            if edge["source"] not in positions or edge["target"] not in positions:
                continue
            x0, y0 = positions[edge["source"]]
            x1, y1 = positions[edge["target"]]
            fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                               text="", showarrow=True, arrowhead=3, arrowsize=1.1, arrowwidth=1.6,
                               arrowcolor="#6ea8ff" if edge.get("strength") == "stronger heuristic" else "#b18cff",
                               opacity=0.9)
            fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(color="#49638b" if edge.get("strength") == "stronger heuristic" else "#77619b", width=1.4, dash="solid"),
                hoverinfo="text", text=[edge.get("reason", "Possible relationship"), edge.get("reason", "Possible relationship")],
                showlegend=False))
        # Node styling reflects the role found by the analysis rules.
        role_colors = {"change":"#ffb454", "symptom":"#ff647c", "normal/context":"#52c7a5", "event":"#8ca4c8"}
        for role in ["change", "symptom", "normal/context", "event"]:
            subset = node_df[node_df["role"] == role]
            if subset.empty:
                continue
            xs, ys, hover, labels, sizes, custom_ids = [], [], [], [], [], []
            for _, n in subset.iterrows():
                x, y = positions[str(n["id"])]
                xs.append(x); ys.append(y)
                labels.append(str(n["service"]) + " · " + str(n["event_id"]))
                hover.append(f"<b>{n['service']} · {n['event_id']}</b><br>Time: {n['time']}<br>Role: {role}<br>Type: {n['kind']}<br>Severity: {n['severity']}<br>{n['message']}")
                sizes.append(23 if bool(n.get("leading_hypothesis", False)) else 16)
                custom_ids.append(str(n["id"]))
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers+text", name=role.title(), text=labels,
                textposition="bottom center", textfont=dict(size=10, color="#dce6f7"),
                marker=dict(size=sizes, color=role_colors[role], line=dict(color="#e8efff", width=1), opacity=0.95),
                hovertext=hover, hoverinfo="text", customdata=custom_ids))
        fig.update_layout(height=max(500, 130*len(service_names)), paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", font_color="#dce6f7", margin=dict(l=20,r=20,t=25,b=35),
            xaxis=dict(title="Minutes from first timestamp (left → right)", showgrid=True, gridcolor="rgba(110,140,180,.15)", zeroline=False),
            yaxis=dict(title="Service lanes", tickmode="array", tickvals=list(lane_y.values()), ticktext=list(lane_y.keys()),
                       showgrid=False, zeroline=False), legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))
        graph_interaction = st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True}, on_select="rerun", selection_mode="points")
        st.caption("Legend: orange = initiating change candidate · red = abnormal/symptom event · green = normal/context signal · blue/purple arrows = possible inferred links. Hover over nodes and links for details.")
        # Clicking a node selects the corresponding event in the inspector.
        node_options = list(range(len(graph["nodes"])))
        selected_node_index_default = 0
        selected_points = graph_interaction.selection.points if hasattr(graph_interaction, "selection") else []
        if selected_points:
            clicked_id = selected_points[-1].get("customdata")
            clicked_index = next((i for i, node in enumerate(graph["nodes"]) if node["id"] == str(clicked_id)), None)
            previous_click = st.session_state.get("causal_graph_last_click")
            if clicked_index is not None and str(clicked_id) != previous_click:
                st.session_state["causal_graph_node"] = clicked_index
                st.session_state["causal_graph_last_click"] = str(clicked_id)
                selected_node_index_default = clicked_index
        selected_node_index = st.selectbox("Inspect an event node", node_options,
            index=selected_node_index_default,
            format_func=lambda i: f"{graph['nodes'][i]['service']} · {graph['nodes'][i]['event_id']} · {graph['nodes'][i]['time']}", key="causal_graph_node")
        selected_node = graph["nodes"][selected_node_index]
        with st.container(border=True):
            st.markdown(f"### {selected_node['service']} · {selected_node['event_id']}")
            st.write(f"**Role:** {selected_node['role']} · **Type:** {selected_node['kind']} · **Severity:** {selected_node['severity']}")
            st.write(f"**Time:** {selected_node['time']}")
            st.write(selected_node["message"] or "No message supplied.")
            related_edges = [e for e in graph["edges"] if e["source"] == selected_node["id"] or e["target"] == selected_node["id"]]
            if related_edges:
                st.markdown("**Relationships inferred by the analysis**")
                for e in related_edges:
                    other_id = e["target"] if e["source"] == selected_node["id"] else e["source"]
                    other = next((n for n in graph["nodes"] if n["id"] == other_id), None)
                    direction = "→" if e["source"] == selected_node["id"] else "←"
                    st.markdown(f"- `{selected_node['event_id']}` {direction} `{other.get('event_id', other_id) if other else other_id}` — **{e['label']}** ({e['minutes_apart']} min). {e['reason']}")
            else:
                st.info("No defensible graph edge was inferred for this event. That is preferable to inventing a relationship.")
        if graph["edges"]:
            st.markdown("#### Relationship audit")
            st.dataframe(pd.DataFrame(graph["edges"])[["source","target","label","minutes_apart","strength","reason","status"]], use_container_width=True, hide_index=True)
        else:
            st.info("No causal links could be inferred from this data. Check timestamps, event messages and explicit service/dependency references.")
        st.download_button("Download analysis graph (JSON)", data=__import__("json").dumps(graph, indent=2, default=str), file_name="rootcause_causal_hypothesis_graph.json", mime="application/json")
    else:
        st.info("No event nodes are available. Load the demo or provide a valid CSV to generate the graph.")

with tab7:
    st.subheader("Modules 3, 4, 5 & 6 · Hypotheses, historical context, recovery draft, next test")
    similar = retrieve_similar_capsules(display_events)
    st.markdown("#### Module 3 · Evidence-aware competing hypotheses")
    if analysis["candidates"]:
        for i, c in enumerate(analysis["candidates"], 1):
            comparison = compare_candidate_evidence(c, display_events)
            st.markdown(f"**Hypothesis {i}: {c['cause']}** — {c['service']} · heuristic score {c['score']*100:.0f}/100 · {c['status']}")
            st.write("Supporting evidence IDs:", ", ".join(str(row["event_id"]) for row in comparison["supporting"]) or "None")
            contradictory_ids = [str(row["event_id"]) for row in comparison["contradictory"]]
            st.write("Potential contradictory/normal signals:", ", ".join(contradictory_ids) or "No normal signal found in the candidate service window; absence is not proof.")
            st.write("Missing evidence:", "; ".join(comparison["missing"]))
    else:
        st.info("No candidate hypothesis is available. Collect initiating-change records and symptom telemetry.")
    st.divider()
    st.markdown("#### Module 4 · Historical capsule retrieval")
    if similar:
        st.dataframe(pd.DataFrame(similar)[["id","title","status","cause","similarity","outcomes","warning"]], use_container_width=True, hide_index=True)
    else:
        st.info("No similar historical capsule exists yet. Similarity search becomes useful after you save reviewed incidents.")
    st.divider()
    recovery = draft_recovery(analysis["candidates"], display_events, similar)
    diagnostic = next_diagnostic_test(analysis["candidates"], display_events)
    st.markdown("#### Module 5 · Historical recovery drafting")
    st.write(recovery["diagnosis"])
    for action in recovery["actions"]:
        st.markdown(f"- **{action['status']}** {action['action']}  \n  Basis: {action['basis']}")
    st.write("**Missing information:**", "; ".join(recovery["missing"]))
    st.warning(recovery["approval"])
    recovery_sections = [
        ("Proposed diagnosis", recovery.get("diagnosis", "Insufficient evidence.")),
        ("Proposed actions — human approval required", [
            f"{a.get('status', 'PROPOSED')} — {a.get('action', '')} | Basis: {a.get('basis', 'Not specified')}"
            for a in recovery.get("actions", [])
        ] or ["No recovery actions proposed."]),
        ("Missing information", recovery.get("missing", []) or ["None listed."]),
        ("Approval and safety", recovery.get("approval", "No action has been executed.")),
        ("Next best diagnostic test", [
            f"Test: {diagnostic.get('test', 'Not available')}",
            f"Why: {diagnostic.get('why', 'Not available')}",
            f"If positive: {diagnostic.get('if_positive', 'Not available')}",
            f"If negative: {diagnostic.get('if_negative', 'Not available')}",
            f"Risk: {diagnostic.get('risk', 'Not specified')}",
        ]),
    ]
    recovery_pdf = build_readable_pdf("Proposed Recovery and Diagnostic Plan", recovery_sections)
    st.download_button("Download readable recovery plan (PDF)", data=recovery_pdf,
                       file_name="rootcause_recovery_plan.pdf", mime="application/pdf")
    st.divider()
    st.markdown("#### Module 6 · Next best diagnostic test")
    st.markdown(f"**Recommended read-only test:** {diagnostic['test']}")
    st.write("**Why:**", diagnostic["why"])
    st.write("**If result supports the hypothesis:**", diagnostic["if_positive"])
    st.write("**If result does not support it:**", diagnostic["if_negative"])
    st.caption(diagnostic["risk"])

st.divider()
st.markdown('<div class="small-muted">ROOTCAUSE AI · Hackathon prototype · Synthetic demo data by default · No automatic remediation</div>', unsafe_allow_html=True)
