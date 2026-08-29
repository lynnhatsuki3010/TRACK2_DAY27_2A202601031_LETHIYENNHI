# Incident Report

## Severity
P2 — CEO revenue dashboard under-reports for the affected day; no data corruption, but decisions made off the dashboard during the window are unreliable. Not P1 because the pipeline can be fixed by re-ingestion with no data loss (source file still exists upstream).

## Summary
`make reset && python scripts/inject_fault.py volume_drop && make baseline` — simulated a partial-ingestion fault: the orders extract job wrote only 150 of the expected ~600 daily order rows (75% row-count drop), then the pipeline reported `SUCCESS`. No schema was violated, no primary key was duplicated, and no null/accepted-value/range rule fired, so **the deterministic contract layer (`src/contract_validator.py`) saw a clean batch: 0 failed checks, 0 critical failures.** The only layer that caught the fault was statistical anomaly detection on row count.

## Detection
- Signal: `detect_metric(150, history, method="auto", context={...})` → `is_anomaly=True`.
- First observed time: 2026-08-29T02:5x UTC, during `make baseline` immediately after fault injection (rehearsal run; in a live incident this is the first `make baseline`/scheduled check after the bad ingestion completes).
- Contract layer signal: none (`failed_contract_checks=0`, `critical_contract_failures=0`) — this is the core lesson: **pipeline `SUCCESS` and 0 contract failures do not mean the data is right.**

## Root Cause
Upstream ingestion job stopped after writing 150/600 rows (e.g. truncated extract, early process kill, or a paginated source that stopped after the first page) but exited without raising an error, so the orchestrator marked the run `SUCCESS`. Nothing in the declared `orders_contract.yaml` (not-null/unique/accepted_values/range/type/freshness on individual columns) encodes an expectation about *how many* rows a healthy batch should have — that expectation only exists implicitly in the historical row-count distribution, which is exactly what statistical anomaly detection is for.

## Evidence
1. **Contract validation — clean (false negative for this fault class):** `validate_orders(orders_df, "contracts/orders_contract.yaml")` → 0 failed issues, 0 critical. Proves row-count drops are structurally invisible to per-column deterministic rules.
2. **Anomaly detection — caught it, and shows why naive z-score is not enough:**
   - Naive full-14-day z-score (mixing weekday ~560-650 rows and weekend ~245-275 rows into one baseline) on the dropped value (150): `is_anomaly=False, score=2.27` (mean=494.6, std=151.6) — **a naive baseline would have missed this real drop**, because weekend rows in the history inflate the standard deviation enough to swallow a 75% drop.
   - Same value (150) compared against its own same-weekday segment via `detect_metric(150, history, method="auto", context={"same_segment_history": [...]})`: `is_anomaly=True, score=10.94, method=auto:mad` — caught, once the detector compares like-for-like days instead of the whole mixed week.
   - `make baseline` end-to-end after the fault: `orders_rows=150` (vs. healthy 600), `row_count_anomaly.is_anomaly=True`.
3. **Blast radius (lineage):** `downstream_assets(dataset_lineage, "stg_orders")` → `["fct_daily_revenue", "ceo_revenue_dashboard"]`; column-level `column_downstream(column_lineage, "raw_orders.amount")` → `["stg_orders.amount_usd", "fct_daily_revenue.daily_revenue", "ceo_revenue_dashboard.revenue"]`. Confirms the CEO-facing revenue figure is the exact terminal node downstream of the missing rows.
4. **SLO framing:** treating "did this batch pass anomaly-free" as the SLI, one bad check out of one recent check gives `slo_status(0.995, bad_events=1, total_events=1)` → `actual_bad_rate=1.0`, `burn_rate≈200x`, `breached=True` — an immediate, unambiguous budget breach for the affected window, which is exactly the kind of spike `multiwindow_burn` is designed to corroborate against the longer window before paging (see `observability/slo.py`).

## Blast Radius
```text
raw_orders (75% of rows missing)
-> stg_orders (view, passes through whatever it's given)
-> fct_daily_revenue (undercounts completed_order_rows and daily_revenue for the affected date)
-> ceo_revenue_dashboard (shows a revenue "drop" that is actually a data-completeness bug, not a real business decline)
```
Support Agent / RAG path (`kb_documents -> kb_active_docs -> rag_index -> support_agent`) is not affected by this specific fault — orders and knowledge-base ingestion are independent pipelines in `data/baseline/lineage_graph.json`.

## Mitigation
1. Quarantine the CEO dashboard's revenue panel for the affected date (annotate as "data quality investigation in progress") to prevent decisions being made off a false revenue-drop signal.
2. Re-run the orders ingestion job for the affected date from source; do not backfill by interpolation, since the missing 450 rows are real transactions, not statistical noise.
3. Once re-ingested, re-run `make baseline` to confirm row count and anomaly status return to normal before un-quarantining the dashboard panel.

## Recovery
`make reset` restores the healthy 600-row baseline (in this rehearsal, simulating a successful re-ingestion). Re-running `make baseline` afterward confirms:
- `orders_rows` back to 600.
- `row_count_anomaly.is_anomaly=False` against the correct same-weekday segment.
- `failed_contract_checks=0` (already was 0 — this layer never signaled the problem either way).

## Verification
- [x] Contract healthy — `failed_contract_checks=0` (never flagged, by design of this fault class — deterministic checks aren't the layer that catches row-count faults).
- [x] dbt tests healthy — `dbt build` after reset: 22/22 pass (2 seeds, 3 models, 14 data tests, 3 unit tests).
- [x] anomaly returned to expected range — re-verified after `make reset`.
- [x] SLO healthy / budget understood — burn rate returns to ~0 once the anomalous check no longer counts as "bad".
- [x] downstream output verified — `fct_daily_revenue`/`ceo_revenue_dashboard` blast radius re-checked via `downstream_assets`.

## Prevention / Action Items
| Action | Owner | Deadline | Why |
|---|---|---|---|
| Add a row-count freshness/volume SLA to the ingestion orchestrator itself (fail the job, not just the downstream check, if row count is implausibly low) | Data Eng | +1 week | Contract/anomaly layers are a safety net, not a substitute for the ingestion job knowing it under-delivered. |
| Make `detect_metric(method="auto")` context-aware by default in every caller (not just `run_baseline.py`'s manual day-of-week preprocessing) so seasonality-aware detection is the default path, not opt-in | Data Reliability | +2 weeks | This incident's own naive-baseline evidence (score 2.27, missed) vs. segmented evidence (score 10.94, caught) shows the default matters. |
| Add a `row_count` range/volume check to `orders_contract.yaml` as a coarse backstop (e.g. `min` rows per batch) even though the primary detection layer is statistical | Data Reliability | +2 weeks | Defense in depth — don't rely on a single layer (this incident's contract layer had zero visibility into the fault). |
| Wire KB/RAG freshness (`stale_kb` fault) into the same `make baseline` report as a named SLO, not just an unused metric | Data Reliability | +3 weeks | Currently `observability/rag_metrics.py`/SLO for the KB path is implemented but not surfaced end-to-end in `scripts/run_baseline.py`'s report; same blind spot exists for the support-agent path. |
