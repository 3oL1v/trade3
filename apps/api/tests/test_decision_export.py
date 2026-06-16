import csv
import io
from datetime import UTC, datetime

from trade3_api.decision_export import decisions_to_csv
from trade3_api.decision_models import (
    DecisionAction,
    DecisionDirection,
    ManualDecision,
)

_EXPECTED_HEADER = (
    "id,symbol,action,direction,ai_verdict,ai_conviction,agreed_with_ai,"
    "decision_price,recorded_at,snapshot_generated_at,note,"
    "outcome_price,outcome_at,outcome_return_pct,outcome_note,"
    "benchmark_symbol,benchmark_price,benchmark_outcome_price,"
    "benchmark_return_pct,excess_return_pct"
)

_RECORDED_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_OUTCOME_AT = datetime(2026, 6, 2, 12, 0, 0, tzinfo=UTC)
_SNAPSHOT_AT = datetime(2026, 6, 1, 11, 55, 0, tzinfo=UTC)


def _full_decision() -> ManualDecision:
    return ManualDecision(
        id=1,
        symbol="BTCUSDT",
        action=DecisionAction.ACCEPT,
        direction=DecisionDirection.LONG,
        ai_verdict="long_candidate",
        ai_conviction="high",
        agreed_with_ai=True,
        decision_price=65000.0,
        snapshot_generated_at=_SNAPSHOT_AT,
        recorded_at=_RECORDED_AT,
        note="strong breakout",
        outcome_price=66300.0,
        outcome_at=_OUTCOME_AT,
        outcome_return_pct=0.02,
        outcome_note="target hit",
        benchmark_symbol="BTCUSDT",
        benchmark_price=65000.0,
        benchmark_outcome_price=66300.0,
        benchmark_return_pct=0.02,
        excess_return_pct=0.0,
        analysis_snapshot={"bias": "up"},
        ai_review={"verdict": "long_candidate"},
    )


def _minimal_decision() -> ManualDecision:
    return ManualDecision(
        id=2,
        symbol="ETHUSDT",
        action=DecisionAction.REJECT,
        direction=DecisionDirection.NONE,
        ai_verdict=None,
        ai_conviction=None,
        agreed_with_ai=None,
        decision_price=None,
        snapshot_generated_at=None,
        recorded_at=_RECORDED_AT,
        note=None,
        outcome_price=None,
        outcome_at=None,
        outcome_return_pct=None,
        outcome_note=None,
        benchmark_symbol=None,
        benchmark_price=None,
        benchmark_outcome_price=None,
        benchmark_return_pct=None,
        excess_return_pct=None,
        analysis_snapshot=None,
        ai_review=None,
    )


def test_header_matches_expected_columns() -> None:
    result = decisions_to_csv([])
    rows = list(csv.reader(io.StringIO(result)))
    assert ",".join(rows[0]) == _EXPECTED_HEADER


def test_row_count_with_two_decisions() -> None:
    result = decisions_to_csv([_full_decision(), _minimal_decision()])
    rows = list(csv.reader(io.StringIO(result)))
    # First row is header; remaining rows are data
    assert len(rows) == 3  # 1 header + 2 data rows


def test_full_decision_cell_values() -> None:
    result = decisions_to_csv([_full_decision()])
    rows = list(csv.reader(io.StringIO(result)))
    data_row = rows[1]
    header = rows[0]
    idx = {col: i for i, col in enumerate(header)}

    assert data_row[idx["symbol"]] == "BTCUSDT"
    assert data_row[idx["action"]] == "accept"
    assert data_row[idx["direction"]] == "long"
    assert data_row[idx["agreed_with_ai"]] == "true"
    assert data_row[idx["decision_price"]] == "65000.0"
    assert data_row[idx["outcome_return_pct"]] == "0.02"
    assert data_row[idx["recorded_at"]] == _RECORDED_AT.isoformat()
    assert data_row[idx["snapshot_generated_at"]] == _SNAPSHOT_AT.isoformat()


def test_minimal_decision_none_fields_are_empty_string() -> None:
    result = decisions_to_csv([_minimal_decision()])
    rows = list(csv.reader(io.StringIO(result)))
    data_row = rows[1]
    header = rows[0]
    idx = {col: i for i, col in enumerate(header)}

    assert data_row[idx["ai_verdict"]] == ""
    assert data_row[idx["agreed_with_ai"]] == ""
    assert data_row[idx["decision_price"]] == ""
    assert data_row[idx["outcome_price"]] == ""
    assert data_row[idx["outcome_at"]] == ""
    assert data_row[idx["snapshot_generated_at"]] == ""
    assert data_row[idx["symbol"]] == "ETHUSDT"
    assert data_row[idx["action"]] == "reject"


def test_analysis_snapshot_and_ai_review_excluded() -> None:
    result = decisions_to_csv([_full_decision()])
    rows = list(csv.reader(io.StringIO(result)))
    header_cols = rows[0]
    assert "analysis_snapshot" not in header_cols
    assert "ai_review" not in header_cols


def test_empty_list_produces_only_header() -> None:
    result = decisions_to_csv([])
    non_empty_lines = [ln.strip() for ln in result.split("\n") if ln.strip()]
    assert len(non_empty_lines) == 1
    assert non_empty_lines[0] == _EXPECTED_HEADER
