"""Deterministic, evidence-aware building blocks for the six RootCause AI modules.
All outputs are hypotheses/drafts; this module never executes remediation.
"""
from __future__ import annotations
import json, re, sqlite3
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

DB_PATH = Path(__file__).with_name("incident_memory.sqlite3")

def _text(row):
    return " ".join(str(row.get(k, "") or "") for k in ("service", "type", "severity", "message", "source")).lower()

def build_dependency_graph(raw_events, candidates=None):
    """Build an evidence-linked *hypothesis* graph from incident events.

    Nodes are event records. Directed edges are generated only from transparent
    heuristics: change -> later abnormality, explicit service references, or
    sequential abnormal events with a matching dependency reference. Edges are
    never presented as proof of causation.
    """
    df = raw_events.copy()
    if df.empty:
        return {"nodes": [], "edges": [], "summary": {"event_count": 0, "edge_count": 0, "leading_hypothesis": None}}
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    for c in ["time", "service", "type", "severity", "message", "event_id", "source"]:
        if c not in df:
            df[c] = ""
    for c in ["time", "service", "type", "severity", "message", "event_id", "source"]:
        df[c] = df[c].fillna("").astype(str).str.strip()
    # Coerce timezone mixtures to UTC so comparisons remain safe.
    df["_time"] = pd.to_datetime(df["time"], errors="coerce", format="mixed", utc=True)
    df = df.reset_index(drop=True)

    normal_re = re.compile(r"\b(normal|within normal range|remains normal|no errors|healthy|stable|recovered|back to normal|returned to normal)\b", re.I)
    abnormal_re = re.compile(r"timeout|latency|error|exhaust|queue|retry|delay|failed|spike|increased|growth|refused|saturat|overload|wait", re.I)
    change_re = re.compile(r"config|change|deploy|release|rollback|updated|modified|restart", re.I)
    recovery_re = re.compile(r"recovered|recovery|restored|back to normal|rolled back", re.I)

    def text_of(row):
        return " ".join(str(row.get(k, "") or "") for k in ("service", "type", "severity", "message", "source")).lower()

    def is_normal(row):
        return bool(normal_re.search(text_of(row)))

    def is_abnormal(row):
        if is_normal(row):
            return False
        return bool(abnormal_re.search(text_of(row))) or bool(re.search(r"critical|error|high", str(row.get("severity", "")), re.I))

    def is_change(row):
        text = text_of(row)
        if recovery_re.search(text):
            return False
        return bool(change_re.search(str(row.get("type", "")) + " " + str(row.get("message", ""))))

    nodes, id_by_index = [], {}
    for i, r in df.iterrows():
        eid = r["event_id"] or f"event-{i+1}"
        # Ensure duplicate/missing IDs cannot collapse graph nodes.
        node_id = eid if eid not in id_by_index.values() else f"{eid}-{i+1}"
        id_by_index[i] = node_id
        role = "normal/context" if is_normal(r) else ("change" if is_change(r) else ("symptom" if is_abnormal(r) else "event"))
        nodes.append({
            "id": node_id,
            "event_id": eid,
            "label": f"{r['service'] or 'unknown service'} · {str(r['message'])[:66]}",
            "service": r["service"] or "unknown service",
            "kind": r["type"], "time": r["time"], "severity": r["severity"],
            "message": r["message"], "source": r["source"], "role": role,
            "is_normal": is_normal(r), "is_change": is_change(r), "is_abnormal": is_abnormal(r),
        })

    edges, edge_keys = [], set()
    valid = df[df["_time"].notna()].sort_values("_time", kind="stable")

    def add_edge(i, j, label, strength, reason, minutes):
        source, target = id_by_index[i], id_by_index[j]
        if source == target or (source, target) in edge_keys:
            return
        edge_keys.add((source, target))
        edges.append({"source": source, "target": target, "label": label,
                      "minutes_apart": round(float(minutes), 1), "strength": strength,
                      "reason": reason, "status": "possible causal link — verify; not proof"})

    # Change -> abnormal symptom within a 60-minute window. Same-service evidence
    # is strongest; cross-service requires the symptom text to name the changed service.
    changes = [i for i in valid.index if is_change(df.loc[i])]
    symptoms = [i for i in valid.index if is_abnormal(df.loc[i])]
    for i in changes:
        a = df.loc[i]
        for j in symptoms:
            b = df.loc[j]
            mins = (b["_time"] - a["_time"]).total_seconds() / 60
            if mins < 0 or mins > 60 or i == j:
                continue
            same_service = bool(a["service"]) and a["service"].lower() == b["service"].lower()
            explicit = bool(a["service"]) and bool(re.search(r"\b" + re.escape(a["service"]) + r"\b", str(b["message"]), re.I))
            if same_service:
                add_edge(i, j, "change → service symptom", "stronger heuristic", "A change precedes an abnormal event in the same service.", mins)
            elif explicit:
                add_edge(i, j, "change → referenced dependency symptom", "moderate heuristic", f"The later event explicitly mentions service '{a['service']}'.", mins)

    # Connect abnormal events when later text explicitly names the earlier service,
    # representing a potential downstream propagation path.
    abnormal_indices = sorted(symptoms, key=lambda i: df.loc[i, "_time"])
    for pos, i in enumerate(abnormal_indices):
        a = df.loc[i]
        if not a["service"]:
            continue
        for j in abnormal_indices[pos+1:]:
            b = df.loc[j]
            mins = (b["_time"] - a["_time"]).total_seconds() / 60
            if mins > 30:
                break
            if a["service"].lower() != b["service"].lower() and re.search(r"\b" + re.escape(a["service"]) + r"\b", str(b["message"]), re.I):
                add_edge(i, j, "referenced dependency path", "moderate heuristic", f"Later event in {b['service']} names {a['service']}.", mins)

    # Tie the graph to the ranked hypothesis engine. Add clearly labelled links
    # from the leading change candidate to its selected evidence records, then
    # highlight the candidate node. These are evidence links, not causal proof.
    candidates = candidates or []
    leading = None
    if candidates:
        top = candidates[0]
        matches = [n for n in nodes if n["service"].lower() == str(top.get("service", "")).lower()
                   and str(n["time"]) == str(top.get("event_time", ""))
                   and n["is_change"]]
        if not matches:
            matches = [n for n in nodes if n["service"].lower() == str(top.get("service", "")).lower()
                       and n["is_change"] and str(top.get("cause", "")).lower() in n["message"].lower()]
        if matches:
            leading = matches[0]["id"]
            id_by_event = {n["event_id"]: n["id"] for n in nodes}
            top_ids = set(str(x) for x in top.get("evidence_ids", []))
            for eid in top_ids:
                target = id_by_event.get(eid)
                if target and target != leading:
                    source_node = next(n for n in nodes if n["id"] == leading)
                    target_node = next(n for n in nodes if n["id"] == target)
                    a_time = pd.to_datetime(source_node["time"], errors="coerce", format="mixed")
                    b_time = pd.to_datetime(target_node["time"], errors="coerce", format="mixed")
                    mins = abs((b_time-a_time).total_seconds()/60) if pd.notna(a_time) and pd.notna(b_time) else 0
                    add_edge(next(i for i, nid in id_by_index.items() if nid == leading),
                             next(i for i, nid in id_by_index.items() if nid == target),
                             "ranked hypothesis → selected evidence", "analysis evidence link",
                             "The root-cause engine included this event in the leading candidate's evidence set; inspect it to verify relevance.", mins)
    if leading is None:
        change_degree = {id_by_index[i]: 0 for i in changes}
        for edge in edges:
            if edge["source"] in change_degree:
                change_degree[edge["source"]] += 1
        leading = max(change_degree, key=change_degree.get) if change_degree and max(change_degree.values(), default=0) > 0 else None
    for node in nodes:
        node["leading_hypothesis"] = node["id"] == leading

    return {
        "nodes": nodes, "edges": edges,
        "summary": {
            "event_count": len(nodes), "edge_count": len(edges),
            "change_count": len(changes), "abnormal_event_count": len(symptoms),
            "normal_context_count": sum(n["is_normal"] for n in nodes),
            "leading_hypothesis": leading,
            "interpretation": "Graph links are rule-inferred hypotheses. Verify with telemetry and service ownership; sequence alone does not prove causation."
        }
    }

def _tokens(text):
    stop = {"the","and","from","with","this","that","was","were","into","for","after","before","service","event","normal","remains","within"}
    return {t for t in re.findall(r"[a-z0-9]+", str(text).lower()) if len(t)>2 and t not in stop}


def compare_candidate_evidence(candidate, events):
    """Separate directly linked support from nearby contradictory normal signals."""
    if events is None or events.empty:
        return {"supporting": [], "contradictory": [], "missing": ["Incident event evidence"]}
    frame = events.copy()
    for column in ("event_id", "service", "type", "message", "time"):
        if column not in frame:
            frame[column] = ""
    frame["_time"] = pd.to_datetime(frame["time"], errors="coerce", format="mixed", utc=True)
    evidence_ids = {str(value) for value in candidate.get("evidence_ids", [])}
    supporting = frame[frame["event_id"].astype(str).isin(evidence_ids)]
    service = str(candidate.get("service", "")).strip().lower()
    candidate_time = pd.to_datetime(candidate.get("event_time", ""), errors="coerce", format="mixed", utc=True)
    relevant = frame[frame["service"].astype(str).str.lower().eq(service)] if service else frame.iloc[0:0]
    if pd.notna(candidate_time):
        relevant = relevant[
            relevant["_time"].isna()
            | ((relevant["_time"] >= candidate_time) & (relevant["_time"] <= candidate_time + pd.Timedelta(hours=1)))
        ]
    else:
        # Without a parseable candidate time, unrelated normal events cannot be
        # assigned to its window and must not be presented as contradictions.
        relevant = relevant.iloc[0:0]
    normal_pattern = re.compile(r"\b(normal|within normal range|remains normal|no errors|healthy|stable)\b", re.I)
    contradiction_mask = relevant.apply(
        lambda row: normal_pattern.search(f"{row['message']} {row['type']}") is not None
        and str(row["event_id"]) not in evidence_ids,
        axis=1,
    )
    contradictory = relevant[contradiction_mask]
    available_types = " ".join(frame["type"].astype(str).str.lower().tolist())
    missing = []
    if "metric" not in available_types:
        missing.append("Before/after service metrics")
    if "trace" not in available_types:
        missing.append("A trace/span view for the suspected dependency path")
    if pd.isna(candidate_time):
        missing.append("A valid timestamp for the candidate event")
    if not missing:
        missing.append("Independent verification by the incident owner")
    return {
        "supporting": supporting.drop(columns=["_time"], errors="ignore").to_dict("records"),
        "contradictory": contradictory.drop(columns=["_time"], errors="ignore").to_dict("records"),
        "missing": missing,
    }

def retrieve_similar_capsules(raw_events, limit=5, db_path=DB_PATH):
    current = " ".join(_text(r) for _, r in raw_events.iterrows())
    terms = _tokens(current)
    if not Path(db_path).exists(): return []
    con = None
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute("SELECT id, title, created_at, status, cause, summary, tags, outcomes FROM capsules ORDER BY created_at DESC").fetchall()
    except sqlite3.Error:
        return []
    finally:
        if con is not None:
            con.close()
    out=[]
    for row in rows:
        rid,title,created,status,cause,summary,tags,outcomes=row
        other=_tokens(" ".join([title,cause,summary,tags,outcomes]))
        overlap=len(terms & other)/max(1,len(terms | other))
        if overlap>0: out.append({"id":rid,"title":title,"created_at":created,"status":status,"cause":cause,"summary":summary,"outcomes":outcomes,"similarity":round(overlap,3),"warning":"Similarity is lexical, not a guarantee this incident is the same."})
    return sorted(out,key=lambda x:x["similarity"],reverse=True)[:limit]

def save_capsule(title, status, cause, summary, evidence_ids, diagnostic_tests, recovery_actions, outcome, db_path=DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS capsules (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,created_at TEXT,status TEXT,cause TEXT,summary TEXT,tags TEXT,outcomes TEXT,evidence TEXT,tests TEXT,actions TEXT)")
            con.execute("INSERT INTO capsules(title,created_at,status,cause,summary,tags,outcomes,evidence,tests,actions) VALUES(?,?,?,?,?,?,?,?,?,?)", (title,datetime.now(timezone.utc).isoformat(),status,cause,summary," ".join(_tokens(title+" "+cause+" "+summary)),outcome,json.dumps(evidence_ids),json.dumps(diagnostic_tests),json.dumps(recovery_actions)))
    finally:
        con.close()
    return True

def draft_recovery(candidates, events, similar_capsules):
    if not candidates: return {"diagnosis":"Insufficient evidence to draft a specific diagnosis.","actions":[],"missing":["A candidate initiating event","Service dependency and source telemetry"],"approval":"Human approval required; no action has been executed."}
    top=candidates[0]
    ids=set(top.get("evidence_ids",[]))
    ev=events[events["event_id"].astype(str).isin(ids)] if "event_id" in events else events.iloc[0:0]
    symptoms=ev[ev.apply(lambda r: bool(re.search(r"timeout|latency|error|exhaust|queue|retry|delay|failed|increased",_text(r))),axis=1)]
    actions=[{"action":f"Verify the change '{top['cause']}' against the deployment/configuration audit log.","basis":"Candidate event and ranking rationale","status":"PROPOSED — human approval required"}]
    if re.search(r"retry",top["cause"],re.I): actions.append({"action":"Compare retry rate, retry queue depth, and downstream payment latency before and after the change; consider reverting only through the incident process.","basis":"Retry-related candidate; verify metrics first","status":"PROPOSED — human approval required"})
    elif re.search(r"pool|connection",top["cause"],re.I): actions.append({"action":"Check connection-pool saturation, wait time, request queue, and capacity limits; validate safe pool settings before any rollback.","basis":"Connection-pool candidate; verify resource metrics first","status":"PROPOSED — human approval required"})
    else: actions.append({"action":"Run a controlled comparison of the candidate service's metrics and dependency traces before changing production state.","basis":"Generic verification step","status":"PROPOSED — human approval required"})
    if similar_capsules: actions.append({"action":"Review the similar historical capsule and confirm its cause and recovery outcome match this incident before reusing any step.","basis":"Historical capsule retrieval","status":"PROPOSED — human approval required"})
    missing=[]
    if not any("trace" in str(x).lower() for x in ev.get("type",pd.Series(dtype=str))): missing.append("A trace/span view for the suspected dependency path")
    if not any("metric" in str(x).lower() for x in ev.get("type",pd.Series(dtype=str))): missing.append("Before/after service metrics")
    return {"diagnosis":f"Tentative hypothesis: {top['cause']} ({top['service']}); heuristic score {top['score']*100:.0f}/100, not a probability.","evidence_ids":sorted(ids),"actions":actions,"missing":missing or ["Independent verification by the incident owner"],"approval":"Human approval required; no action has been executed."}

def next_diagnostic_test(candidates, events):
    if len(candidates)<2: return {"test":"Inspect before/after metrics and deployment audit logs for the leading candidate.","why":"There are not enough competing hypotheses to choose a discriminating test reliably.","if_positive":"Candidate timing and expected symptom pattern are supported, but causation still needs verification.","if_negative":"Lower confidence in the candidate and inspect other causes or missing telemetry.","risk":"Read-only test; do not change production state."}
    a,b=candidates[0],candidates[1]
    text=(a["cause"]+" "+b["cause"]).lower()
    if "retry" in text:
        test="Compare payment retry rate and queue depth against checkout timeout timestamps, then inspect the payment dependency span."
        pos="Retry growth precedes downstream timeouts and the span shows payment delay: supports the retry hypothesis."
        neg="Retry metrics are normal or time order is inconsistent: weaken the retry hypothesis and compare the second candidate."
    elif "pool" in text or "connection" in text:
        test="Inspect connection-pool utilization, wait time, and exhaustion counters before and after the suspected change."
        pos="Pool saturation rises before dependent-service latency: supports the pool hypothesis."
        neg="Pool metrics remain healthy: weaken the pool hypothesis and test the competing cause."
    else:
        test=f"Compare service-specific metrics and traces for '{a['service']}' versus '{b['service']}' over the incident window."
        pos=f"Abnormality starts in {a['service']} and propagates to dependents: supports candidate 1."
        neg=f"Abnormality starts in {b['service']} or predates candidate 1: investigate candidate 2 or an unobserved cause."
    return {"test":test,"why":f"It distinguishes the leading candidates '{a['cause']}' and '{b['cause']}' using measurable evidence rather than event order alone.","if_positive":pos,"if_negative":neg,"risk":"Read-only diagnostic; human operator decides any follow-up action."}

def capsule_payload(title, status, candidate, events, recovery, tests):
    return {"title":title,"status":status,"cause":candidate.get("cause", "") if candidate else "","summary":recovery.get("diagnosis", ""),"evidence_ids":candidate.get("evidence_ids",[]) if candidate else [],"diagnostic_tests":[tests],"recovery_actions":recovery.get("actions",[]),"outcome":"Unverified — update after incident owner review"}
