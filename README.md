# RootCause AI — Incident Intelligence

A read-only AIOps prototype for incident investigation. It combines a deterministic heuristic root-cause engine with six connected investigation modules. Results are hypotheses, not proof of causation.

## Run locally on Windows

1. Install Python 3.11 or newer from python.org and ensure Python is on PATH.
2. Extract this folder and open it in VS Code.
3. In the terminal, run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m streamlit run app.py
```

If PowerShell blocks activation, use `\.venv\Scripts\python.exe -m pip install -r requirements.txt` and `\.venv\Scripts\python.exe -m streamlit run app.py`.

## Deploy

### Streamlit Community Cloud

1. Upload the contents of this project folder to a private/public GitHub repository as appropriate.
2. In Streamlit Community Cloud, create an app from that repository and select `app.py` as the main file.
3. Ensure `requirements.txt` is at the repository root (the root of this extracted project).
4. Deploy. The built-in demo and CSV workflow do not require API keys.

### Docker

```bash
docker build -t rootcause-ai .
docker run --rm -p 8501:8501 rootcause-ai
```

Open `http://localhost:8501`.

**Persistence warning:** incident capsules are stored in local SQLite (`incident_memory.sqlite3`). On ephemeral hosting, data may be lost on redeploy/restart or when the instance is replaced. For durable hosted use, mount a persistent volume or replace SQLite with a managed database before relying on saved incident history.

## Data sources

### Built-in demo

A synthetic checkout/inventory incident is included. It works offline and is the recommended first demo.

### CSV upload

Expected columns: `time, service, type, severity, message, source, event_id`. Common aliases such as `timestamp`, `datetime`, `service_name`, `event_type`, `level`, `details`, and `id` are normalized. Use ISO-8601 timestamps with timezone when possible. Only upload approved, redacted data.

The `time` and `message` columns are required. Other supported fields are optional. Blank or duplicate event IDs are assigned unique row IDs during upload; malformed timestamps are retained as records but cannot contribute timing evidence. Mixed timezone timestamps are compared on a UTC timeline. Empty files and malformed input produce an error instead of being treated as connected data.

### Prometheus metrics (read-only)

Choose **Connect Prometheus metrics**, enter a reachable Prometheus base URL and a PromQL expression, choose a lookback window, and fetch samples. Example queries: `up` or `rate(http_requests_total[5m])`.

- The connector uses Prometheus HTTP API `query_range` via GET; it does not write to Prometheus.
- A deployed app must be able to reach the configured endpoint. `localhost` refers to the app container/host itself, not automatically your personal computer.
- This connector imports metric samples as observations; it does not infer abnormality thresholds automatically.
- Prometheus auth, TLS client certificates, and private network tunneling are not built into this prototype. Do not expose an unauthenticated Prometheus endpoint publicly.
- Logs, traces and deployment/restart history can be uploaded in the common CSV format. A direct OpenTelemetry/log-platform connector requires a reachable backend and a configured adapter; it is not falsely represented as connected by this version.

## Reports

The Report tab exports a readable multi-page PDF incident report. The diagnostics/recovery tab exports a separate PDF recovery and diagnostic plan. CSV evidence export remains available; the graph JSON export is a technical graph-data export, not the incident report.

## Six modules

1. **Incident Memory Capsules** — stores incident title, verification status, candidate, evidence references, diagnostic tests, proposed actions and outcome in SQLite.
2. **Causal Dependency Graph** — shows possible event links based on explicit references and timing; edges are not proof of causation.
3. **Evidence-Aware Hypotheses** — ranks candidate changes and links relevant evidence. Heuristic scores are not probabilities.
4. **Historical Capsule Retrieval** — finds textually similar prior capsules; similarity does not establish a shared cause.
5. **Historical Recovery Drafting** — drafts evidence-linked suggestions for human review. No remediation is executed.
6. **Next Best Diagnostic Test** — provides deterministic, read-only tests for supported incident patterns.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The test suite covers the ranking engine, capsule persistence/retrieval, graph generation, evidence comparison, read-only diagnostic recommendations, CSV validation and unique event IDs, mixed timezone timestamps, PDF validity/pagination, and a mocked Prometheus API response. The Prometheus test is mocked and does not prove connectivity to your real monitoring server. It does not replace a browser walkthrough of Streamlit or a test against your Prometheus server.

## Capsule storage and backup

Capsules are written to `incident_memory.sqlite3` beside `app.py`. The file is ignored by Git and excluded from the deployment image. Stop the app before copying this file as a simple backup. For a live backup while the app is running, use SQLite's online backup API rather than copying the database file. Treat capsule contents as incident data and store backups in an access-controlled location. The app has no cloud persistence or authentication layer.

## Configuration and secrets

There are no required API keys or environment variables. Prometheus is configured per investigation in the UI and is read-only. Do not place credentials in uploaded CSVs or source files. Prometheus authentication is not supported by this prototype; use an appropriately protected network endpoint.

## Operational and safety limitations

- This is a hackathon prototype, not a production-certified incident response platform.
- It uses deterministic heuristics and text matching, not a trained causal model.
- Scores are prioritization indicators, not calibrated probabilities.
- Event order, text overlap, and recovery after an action do not prove causation.
- The app does not execute recovery actions or change monitored systems.
- For production, add authentication/authorization, durable shared storage, audit logging, rate limits, secret management, data retention controls, observability and a security review.


### PDF export dependency

PDF report downloads use ReportLab. It is listed in `requirements.txt`; after extracting an updated ZIP, run `python -m pip install -r requirements.txt` before launching the app.
