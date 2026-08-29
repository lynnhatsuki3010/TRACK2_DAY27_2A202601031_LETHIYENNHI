"""Contract validator used as the lab baseline.

Deterministic checks: required/not-null, unique, accepted values, numeric
range, declared type, and dataset-level freshness. Every issue also carries
a severity-driven `action` (block / quarantine / warn) so callers can decide
what to do with a failed batch without re-deriving policy from severity.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

# critical -> stop the pipeline; warning -> ship data aside for review;
# info -> let it through but surface the signal.
SEVERITY_ACTION = {
    "critical": "block",
    "warning": "quarantine",
    "info": "warn",
}

_TYPE_CHECKERS = {
    "integer": lambda s: pd.to_numeric(s, errors="coerce"),
    "number": lambda s: pd.to_numeric(s, errors="coerce"),
    "datetime": lambda s: pd.to_datetime(s, errors="coerce", utc=True),
}


def action_for_severity(severity: str) -> str:
    return SEVERITY_ACTION.get(severity, "warn")


def _issue(
    check: str,
    *,
    column: str | None,
    severity: str,
    passed: bool,
    details: str,
) -> dict[str, Any]:
    return {
        "check": check,
        "column": column,
        "severity": severity,
        "passed": bool(passed),
        "details": details,
        "action": action_for_severity(severity) if not passed else "none",
    }


def load_contract(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_dataframe(df: pd.DataFrame, contract: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    columns = contract.get("columns", {})

    for column, rules in columns.items():
        severity = rules.get("severity", "warning")
        required = bool(rules.get("required", False))

        if column not in df.columns:
            if required:
                issues.append(
                    _issue(
                        "required_column",
                        column=column,
                        severity=severity,
                        passed=False,
                        details=f"Missing required column: {column}",
                    )
                )
            continue

        series = df[column]

        if required:
            null_count = int(series.isna().sum())
            issues.append(
                _issue(
                    "not_null",
                    column=column,
                    severity=severity,
                    passed=(null_count == 0),
                    details=f"null_count={null_count}",
                )
            )

        if rules.get("unique"):
            duplicate_count = int(series.duplicated(keep=False).sum())
            issues.append(
                _issue(
                    "unique",
                    column=column,
                    severity=severity,
                    passed=(duplicate_count == 0),
                    details=f"duplicate_rows={duplicate_count}",
                )
            )

        accepted = rules.get("accepted_values")
        if accepted is not None:
            invalid_mask = series.notna() & ~series.isin(accepted)
            invalid_count = int(invalid_mask.sum())
            issues.append(
                _issue(
                    "accepted_values",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}; accepted={accepted}",
                )
            )

        declared_type = rules.get("type")
        coerced: pd.Series | None = None
        if declared_type in _TYPE_CHECKERS:
            coerced = _TYPE_CHECKERS[declared_type](series)
            non_null = series.notna()
            drift_mask = non_null & coerced.isna()
            if declared_type == "integer":
                # accept whole-number floats (e.g. "3.0"), reject real decimals
                fractional_part = (coerced - coerced.round()).abs()
                fractional_mask = coerced.notna() & (fractional_part > 1e-9)
                drift_mask |= fractional_mask
            drift_count = int(drift_mask.sum())
            issues.append(
                _issue(
                    "type",
                    column=column,
                    severity=severity,
                    passed=(drift_count == 0),
                    details=f"declared_type={declared_type}; type_drift_count={drift_count}",
                )
            )

        # Range check reuses the numeric coercion above when the column is
        # already declared integer/number so a type-drift value cannot also
        # silently pass range just because pd.to_numeric coerced it to NaN.
        if "min" in rules or "max" in rules:
            numeric = coerced if declared_type in ("integer", "number") else pd.to_numeric(series, errors="coerce")
            invalid = pd.Series(False, index=series.index)
            if "min" in rules:
                invalid |= numeric < rules["min"]
            if "max" in rules:
                invalid |= numeric > rules["max"]
            invalid_count = int(invalid.fillna(False).sum())
            issues.append(
                _issue(
                    "range",
                    column=column,
                    severity=severity,
                    passed=(invalid_count == 0),
                    details=f"invalid_count={invalid_count}",
                )
            )

    freshness = contract.get("freshness")
    if freshness:
        fcol = freshness.get("column")
        max_delay = freshness.get("max_delay_minutes")
        fseverity = freshness.get("severity", "warning")
        if fcol and fcol in df.columns and max_delay is not None:
            ts = pd.to_datetime(df[fcol], errors="coerce", utc=True)
            latest = ts.max()
            if pd.isna(latest):
                issues.append(
                    _issue(
                        "freshness",
                        column=fcol,
                        severity=fseverity,
                        passed=False,
                        details="no_valid_timestamp",
                    )
                )
            else:
                delay_minutes = (pd.Timestamp(datetime.now(timezone.utc)) - latest).total_seconds() / 60.0
                issues.append(
                    _issue(
                        "freshness",
                        column=fcol,
                        severity=fseverity,
                        passed=(delay_minutes <= max_delay),
                        details=f"delay_minutes={delay_minutes:.1f}; max_delay_minutes={max_delay}",
                    )
                )

    return issues


def failed_issues(issues: list[dict[str, Any]], min_severity: str | None = None) -> list[dict[str, Any]]:
    failed = [i for i in issues if not i.get("passed", False)]
    if min_severity is None:
        return failed
    order = {"info": 0, "warning": 1, "critical": 2}
    threshold = order[min_severity]
    return [i for i in failed if order.get(i.get("severity", "warning"), 1) >= threshold]
