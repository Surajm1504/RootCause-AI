"""Transparent, evidence-linked heuristic root-cause ranking.

Scores are ranking indicators, NOT calibrated probabilities or proof of causation.
"""
import re
import pandas as pd

REQUIRED_COLUMNS = ["time", "service", "type", "severity", "message", "source", "event_id"]
CHANGE_PATTERN = r"config|change|deploy|release|rollback|updated|modified"
SYMPTOM_PATTERN = r"timeout|latency|error|exhaust|wait|queue|failure|unavailable|spike|slow|degrad|retry|increased|growing|delay|failed|refused|saturated|overload"
NORMAL_PATTERN = r"\b(normal|within normal range|remains normal|no errors|healthy|recovered|back to normal|returned to normal|stable)\b"
RECOVERY_PATTERN = r"\b(?:recovered|recovery|restored|back to normal|returned to normal|rolled back|rollback completed|service restarted;.*recovered)\b"


def normalize_events(df):
    """Normalize common CSV column aliases and safely parse event timestamps."""
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    aliases = {
        "timestamp": "time", "datetime": "time", "service_name": "service",
        "event_type": "type", "level": "severity", "log": "message",
        "details": "message", "id": "event_id", "event": "message",
    }
    for old, new in aliases.items():
        if old in df.columns and new not in df.columns:
            df = df.rename(columns={old: new})
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    # Normalize timezone-aware and naive timestamps to one comparable timeline.
    # Naive values are interpreted as UTC; malformed values stay NaT.
    df["_time"] = pd.to_datetime(df["time"], format="mixed", errors="coerce", utc=True)
    return df


def _is_change(row):
    """Identify likely initiating changes, excluding recovery/mitigation events."""
    text = f"{row['type']} {row['message']}".lower()
    if re.search(RECOVERY_PATTERN, text):
        return False
    # A restart/recovery is usually a mitigation, not the initiating cause.
    if re.search(r"\brestart(?:ed)?\b", text) and re.search(r"recover|restor|normal", text):
        return False
    return bool(re.search(CHANGE_PATTERN, text)) or bool(
        re.search(r"\b(config(?:uration)?_change|deployment|deploy|release|restart)\b", str(row["type"]), re.I)
    )


def _is_abnormal(row):
    text = f"{row['message']} {row['severity']}".lower()
    if re.search(NORMAL_PATTERN, text):
        return False
    return bool(re.search(SYMPTOM_PATTERN, text)) or bool(
        re.search(r"critical|error|high", str(row["severity"]), re.I)
    )


def rank_causes(raw_events):
    """Rank plausible initiating changes using time and service/evidence links."""
    events = normalize_events(raw_events)
    if events.empty:
        return {"candidates": [], "unknown": True, "message": "No events were supplied."}

    change_mask = events.apply(_is_change, axis=1)
    symptom_mask = events.apply(_is_abnormal, axis=1)
    changes = events[change_mask].copy()
    symptoms = events[symptom_mask].copy()
    recoveries = events[events["message"].str.contains(RECOVERY_PATTERN, case=False, na=False)].copy()

    if changes.empty:
        return {"candidates": [], "unknown": True, "message": "No likely initiating configuration, deployment, or change events were found."}

    valid_symptoms = symptoms[symptoms["_time"].notna()]
    candidates = []
    for _, change in changes.iterrows():
        ct = change["_time"]
        service = change["service"].strip() or "unknown service"
        message = change["message"].strip() or f"Change event in {service}"
        score = 0.12
        reasons = ["A likely configuration/deployment change was found."]
        ids = [change["event_id"]] if change["event_id"] else []

        if pd.isna(ct):
            reasons.append("Timestamp could not be parsed; timing evidence is unavailable.")
            temporal = valid_symptoms.iloc[0:0]
            same = temporal
            linked = temporal
        else:
            end = ct + pd.Timedelta(minutes=60)
            temporal = valid_symptoms[(valid_symptoms["_time"] >= ct) & (valid_symptoms["_time"] <= end)]
            # Same-service symptoms are directly relevant. Cross-service symptoms are
            # linked only when their text explicitly names the changed service.
            same = temporal[temporal["service"].str.lower() == service.lower()]
            other = temporal[temporal["service"].str.lower() != service.lower()]
            linked_mask = other["message"].str.contains(re.escape(service), case=False, na=False) if service != "unknown service" else pd.Series(False, index=other.index)
            linked = other[linked_mask]

            earlier = valid_symptoms[valid_symptoms["_time"] < ct]
            if earlier.empty:
                score += 0.16
                reasons.append("No earlier abnormal symptom was found in the supplied events.")
            else:
                score -= 0.18
                reasons.append("Abnormal symptoms existed before this change, weakening the timing hypothesis.")

            if len(same):
                score += min(0.11 * len(same), 0.33)
                reasons.append(f"{len(same)} abnormal event(s) followed the change in the same service.")
                ids.extend(x for x in same["event_id"].tolist() if x)
            else:
                reasons.append("No abnormal event was found in the changed service after the change.")

            if len(linked):
                score += min(0.15 * len(linked), 0.30)
                reasons.append(f"{len(linked)} cross-service event(s) explicitly reference {service}.")
                ids.extend(x for x in linked["event_id"].tolist() if x)

            # A general incident elsewhere is weak context, not proof that this
            # particular change caused it. Do not attach unrelated events as evidence.
            unlinked = temporal[~temporal.index.isin(same.index) & ~temporal.index.isin(linked.index)]
            if len(unlinked):
                score += min(0.025 * len(unlinked), 0.05)
                reasons.append(f"{len(unlinked)} other abnormal event(s) occurred in the same window but were not directly linked to this service.")
                # Keep incident-wide abnormal signals as context only when this
                # candidate has at least one direct service/dependency link.
                if len(same) or len(linked):
                    ids.extend(x for x in unlinked["event_id"].tolist() if x)

            # Include a recovery/rollback clue only when it mentions the candidate service.
            recovery_mask = recoveries["_time"].notna() & (recoveries["_time"] >= ct) & (recoveries["_time"] <= end)
            if service != "unknown service":
                recovery_mask &= recoveries["message"].str.contains(re.escape(service), case=False, na=False) | (recoveries["service"].str.lower() == service.lower())
            recovery_evidence = recoveries[recovery_mask]
            if len(recovery_evidence):
                score += 0.08
                reasons.append("A later recovery/rollback event is associated with this service; this is supportive context, not proof.")
                ids.extend(x for x in recovery_evidence["event_id"].tolist() if x)

        # Type/severity can add modest context, never enough to make an unrelated
        # change a strong candidate on its own.
        if re.search(r"config_change|deployment|release", str(change["type"]), re.I):
            score += 0.04
        score = round(max(0.0, min(score, 0.95)), 2)
        status = "Leading hypothesis — verify" if score >= 0.55 else "Weak candidate — verify"
        candidates.append({
            "cause": message, "service": service, "event_time": change["time"],
            "score": score, "reasons": reasons,
            "evidence_ids": list(dict.fromkeys(ids)), "status": status,
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    strong = bool(candidates and candidates[0]["score"] >= 0.55 and (symptom_mask.sum() > 0))
    message = "" if strong else "Evidence is insufficient to identify a strong candidate. Treat rankings as tentative."
    return {"candidates": candidates, "unknown": not strong, "message": message}
