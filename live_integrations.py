"""Optional read-only telemetry adapters for RootCause AI.

Supported directly: Prometheus HTTP API query_range for numeric time series.
Logs/traces/deployments can be normalized from CSV via the main uploader.
No remediation or write APIs are called.
"""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any
import pandas as pd

class IntegrationError(RuntimeError):
    """Safe, user-facing integration error."""


def prometheus_range_events(base_url: str, query: str, minutes: int = 30, step_seconds: int = 60,
                            timeout_seconds: int = 10) -> pd.DataFrame:
    """Fetch a Prometheus range query and convert returned samples to normalized events.

    `base_url` is the Prometheus server root, e.g. http://localhost:9090.
    Query is a PromQL expression. This function only sends a GET request.
    """
    base_url = (base_url or "").strip().rstrip("/")
    query = (query or "").strip()
    if not base_url.startswith(("http://", "https://")):
        raise IntegrationError("Prometheus URL must begin with http:// or https://.")
    if not query:
        raise IntegrationError("Enter a PromQL query before connecting.")
    if not 1 <= int(minutes) <= 1440:
        raise IntegrationError("Time window must be between 1 and 1440 minutes.")
    if not 15 <= int(step_seconds) <= 3600:
        raise IntegrationError("Step must be between 15 and 3600 seconds.")
    end = time.time()
    start = end - int(minutes) * 60
    params = urllib.parse.urlencode({"query": query, "start": str(start), "end": str(end), "step": str(int(step_seconds))})
    url = f"{base_url}/api/v1/query_range?{params}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "RootCauseAI/1.0"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise IntegrationError(f"Prometheus returned HTTP {exc.code}. Check URL, query and access policy.") from exc
    except urllib.error.URLError as exc:
        raise IntegrationError("Could not reach Prometheus. Check the endpoint, network and firewall.") from exc
    except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IntegrationError("Prometheus response timed out or was not valid JSON.") from exc
    if payload.get("status") != "success":
        detail = str(payload.get("error", "query failed"))[:240]
        raise IntegrationError(f"Prometheus query failed: {detail}")
    result = payload.get("data", {}).get("result", [])
    rows = []
    for series_idx, series in enumerate(result):
        labels = series.get("metric", {}) or {}
        service = str(labels.get("service", labels.get("job", labels.get("instance", "prometheus-target"))))
        metric_name = str(labels.get("__name__", query))
        for sample_idx, sample in enumerate(series.get("values", [])):
            try:
                ts = float(sample[0]); value = float(sample[1])
            except (TypeError, ValueError, IndexError):
                continue
            if value != value or value in (float("inf"), float("-inf")):
                continue
            stamp = datetime.fromtimestamp(ts, timezone.utc).isoformat()
            rows.append({
                "time": stamp, "service": service, "type": "metric",
                "severity": "info", "message": f"Prometheus metric {metric_name} = {value:g}; labels={json.dumps(labels, sort_keys=True)}",
                "source": "prometheus", "event_id": f"PROM-{series_idx+1}-{sample_idx+1}",
            })
    if not rows:
        raise IntegrationError("Prometheus query succeeded but returned no usable samples for this time window.")
    return pd.DataFrame(rows)


def validate_event_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the minimal event data contract without dropping source fields."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise IntegrationError("No event rows were provided.")
    if len(frame) > 100_000:
        raise IntegrationError("This prototype limits one upload to 100,000 rows.")
    out = frame.copy()
    out.columns = [str(c).strip().lower().replace(" ", "_") for c in out.columns]
    aliases = {"timestamp":"time", "datetime":"time", "service_name":"service", "event_type":"type", "level":"severity", "details":"message", "id":"event_id"}
    out = out.rename(columns={k:v for k,v in aliases.items() if k in out.columns and v not in out.columns})
    if "time" not in out.columns:
        raise IntegrationError("CSV must include a time/timestamp/datetime column.")
    if not any(c in out.columns for c in ("message", "details")):
        raise IntegrationError("CSV must include a message/details column.")
    for col in ("service", "type", "severity", "message", "source", "event_id"):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)
    out["time"] = out["time"].fillna("").astype(str)
    # Keep every row inspectable even when IDs are absent or duplicated.
    used_ids = set()
    normalized_ids = []
    for index, value in enumerate(out["event_id"].str.strip(), start=1):
        event_id = value or f"CSV-{index:06d}"
        candidate = event_id
        suffix = 2
        while candidate in used_ids:
            candidate = f"{event_id}-{suffix}"
            suffix += 1
        used_ids.add(candidate)
        normalized_ids.append(candidate)
    out["event_id"] = normalized_ids
    return out
