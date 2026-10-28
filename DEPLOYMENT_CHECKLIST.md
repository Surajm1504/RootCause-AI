# Deployment checklist

- [ ] Run `python -m unittest discover -s tests -v` and confirm all tests pass.
- [ ] Launch `python -m streamlit run app.py` and open the local URL.
- [ ] Verify built-in demo, all tabs, CSV upload, CSV download, Markdown report download and capsule save/retrieval.
- [ ] Test a malformed CSV and confirm a helpful error is displayed.
- [ ] Test Prometheus against a non-production endpoint; do not use a public unauthenticated endpoint.
- [ ] Confirm whether the target host has persistent storage before relying on SQLite history.
- [ ] Use synthetic/redacted telemetry for judging and screenshots.
- [ ] Do not describe heuristic scores as probabilities or hypotheses as confirmed causes.
- [ ] Do not claim live logs/traces are connected unless the corresponding backend adapter is configured and tested.
