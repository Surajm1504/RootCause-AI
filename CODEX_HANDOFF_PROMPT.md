# Codex handoff: RootCause AI six-module prototype

You are reviewing and improving an existing Streamlit hackathon prototype. Preserve the current visual design and avoid a wholesale rewrite. First inspect all source files, tests, README and sample CSV. Make a backup or work on a branch before editing.

## Product goal
RootCause AI is a read-only AIOps incident investigation assistant. It correlates logs, metrics, traces and change events, surfaces competing root-cause hypotheses with evidence, and helps humans decide what to verify next. Never execute remediation. Scores are heuristic ranking indicators, not probabilities. Event order alone is not causation.

## Six required modules
1. Incident Memory Capsules: preserve incident events/evidence IDs, hypotheses, diagnostic tests, proposed recovery actions, cause status (suspected/supported/confirmed/unknown) and outcome outside the failing app. Validate persistence, schema migration, privacy and backup behavior.
2. Causal Dependency Graph: link possible event/service relationships using explicit references and temporal context; label edges as possible links and never as proven causes.
3. Evidence-Aware Hypothesis Engine: compare multiple candidate causes, show support, contradictions and missing evidence, handle normal telemetry correctly, and report unknown when insufficient.
4. Historical Capsule Retrieval: find similar saved incidents and show their cause verification status and outcomes. Similarity must not blindly transfer an old fix.
5. Historical Recovery Drafting: draft evidence-linked recovery suggestions, cite the basis, list missing information and require human approval. No automatic changes or command execution.
6. Next Best Diagnostic Test: deterministic, read-only tests that distinguish candidate hypotheses, explain positive/negative outcomes, and admit when data is insufficient.

## Work to do
- Run `python -m unittest discover -s tests -v` and `python -m py_compile app.py root_cause_engine.py incident_modules.py` before edits.
- Inspect and test every tab in `app.py`, especially empty data, malformed CSV, duplicate/missing event IDs, missing/unparseable timestamps, timezone mixtures, and empty service/message values.
- Verify the Payments scenario ranks the retry-limit change above unrelated Catalog change; relevant PAY-102 and PAY-106 evidence should be included while normal CAT-202 and INV-301 should not be supporting evidence.
- Verify built-in demo ranks the inventory pool change above unrelated Catalog change.
- Add tests for each module, persistence and retrieval; no candidate / unknown cases; conflicting or contradictory evidence; duplicate capsule creation; malformed and missing values.
- Fix bugs conservatively. Keep dependencies minimal and document any new dependency.
- Validate Streamlit runtime if the environment supports it. If it does not, state that explicitly; do not claim runtime tests passed.
- Check UI layout and that all downloads contain the correct data. Ensure saved capsule database is not accidentally bundled with demo data or committed with sensitive incident content.
- Update README with setup, test command, supported CSV columns, limitations and how to back up local capsules.

## Acceptance criteria
- Tests pass and test output is reported accurately.
- Existing dark dashboard and demo flow remain usable.
- The six modules are visible and meaningfully connected to the same incident data.
- All causal claims are qualified; candidate status distinguishes suspected/supported/confirmed.
- Historical matching is explainable and does not imply certainty.
- Recovery is only a draft, requires human approval, and is never executed.
- Diagnostic tests are read-only and explain what positive and negative results mean.
- No secrets, API keys, or unredacted sample customer data are added.

At the end, summarize changed files, tests actually run and results, known limitations, and exact run commands. Never claim tests passed unless you ran them.
