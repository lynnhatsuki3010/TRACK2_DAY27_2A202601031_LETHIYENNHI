#!/usr/bin/env python3
"""Great Expectations Core 1.21 flow: Suite + ValidationDefinition + Checkpoint.

Extends the starter single-batch example into a reusable Expectation Suite,
wraps it in a ValidationDefinition/Checkpoint, and derives a severity-aware
action (block / quarantine / warn) from the Checkpoint result instead of a
flat pass/fail.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import great_expectations as gx
except ImportError as exc:  # friendlier classroom failure
    raise SystemExit("great_expectations is not installed. Run: pip install -r requirements.txt") from exc

from src.contract_validator import action_for_severity

# expectation -> severity, mirrors contracts/orders_contract.yaml
EXPECTATION_SEVERITY: list[tuple[Any, str]] = [
    (gx.expectations.ExpectColumnValuesToNotBeNull(column="order_id"), "critical"),
    (gx.expectations.ExpectColumnValuesToBeUnique(column="order_id"), "critical"),
    (gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0), "critical"),
    (gx.expectations.ExpectColumnValuesToBeInSet(column="currency", value_set=["USD", "VND"]), "critical"),
    (
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="status", value_set=["pending", "completed", "refunded", "cancelled"]
        ),
        "warning",
    ),
]


def build_suite(context: "gx.data_context.AbstractDataContext") -> "gx.ExpectationSuite":
    suite = gx.ExpectationSuite(name="orders_suite")
    for expectation, severity in EXPECTATION_SEVERITY:
        expectation.meta = {**(expectation.meta or {}), "severity": severity}
        suite.add_expectation(expectation)
    return context.suites.add(suite)


def resolve_overall_action(result) -> dict[str, Any]:
    """Turn a Checkpoint run result into a severity-aware overall action.

    GX Core 1.x does not natively rank expectation-level severity into a
    single pipeline action, so this walks each expectation result, reads
    back the `severity` meta we attached in build_suite(), and applies the
    same block > quarantine > warn precedence as src.contract_validator.
    """
    order = {"block": 2, "quarantine": 1, "warn": 0, "none": -1}
    worst_action = "none"
    failures: list[dict[str, Any]] = []

    run_result = next(iter(result.run_results.values()))
    for expectation_result in run_result["results"]:
        cfg = expectation_result.expectation_config
        severity = (cfg.meta or {}).get("severity", "warning")
        passed = bool(expectation_result.success)
        action = action_for_severity(severity) if not passed else "none"
        if order[action] > order[worst_action]:
            worst_action = action
        if not passed:
            failures.append(
                {
                    "expectation": cfg.type,
                    "column": cfg.kwargs.get("column"),
                    "severity": severity,
                    "action": action,
                }
            )

    return {"action": worst_action, "failures": failures}


def main() -> None:
    df = pd.read_csv(ROOT / "data" / "incoming" / "orders.csv")
    context = gx.get_context()

    data_source = context.data_sources.add_pandas("orders_pandas")
    asset = data_source.add_dataframe_asset(name="orders_dataframe")
    batch_definition = asset.add_batch_definition_whole_dataframe("whole_orders")

    suite = build_suite(context)

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(name="orders_validation", data=batch_definition, suite=suite)
    )

    checkpoint = context.checkpoints.add(
        gx.Checkpoint(
            name="orders_checkpoint",
            validation_definitions=[validation_definition],
            actions=[gx.checkpoint.UpdateDataDocsAction(name="update_data_docs")],
        )
    )

    result = checkpoint.run(batch_parameters={"dataframe": df})

    for expectation_result in next(iter(result.run_results.values()))["results"]:
        cfg = expectation_result.expectation_config
        print(f"{cfg.type:<40} success={expectation_result.success}")

    outcome = resolve_overall_action(result)
    print(f"\nSuite/Checkpoint result: {'PASS' if result.success else 'FAIL'}")
    print(f"Overall action         : {outcome['action']}")
    for failure in outcome["failures"]:
        print(f"  - {failure['expectation']} column={failure['column']} "
              f"severity={failure['severity']} action={failure['action']}")


if __name__ == "__main__":
    main()
