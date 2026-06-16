import csv
import io
from datetime import datetime

from .decision_models import ManualDecision

_COLUMNS = [
    "id",
    "symbol",
    "action",
    "direction",
    "ai_verdict",
    "ai_conviction",
    "agreed_with_ai",
    "decision_price",
    "recorded_at",
    "snapshot_generated_at",
    "note",
    "outcome_price",
    "outcome_at",
    "outcome_return_pct",
    "outcome_note",
    "benchmark_symbol",
    "benchmark_price",
    "benchmark_outcome_price",
    "benchmark_return_pct",
    "excess_return_pct",
]


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    # StrEnum fields: str() gives the value directly
    return str(value)


def decisions_to_csv(decisions: list[ManualDecision]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_COLUMNS)
    for d in decisions:
        writer.writerow([
            _cell(d.id),
            _cell(d.symbol),
            _cell(d.action),
            _cell(d.direction),
            _cell(d.ai_verdict),
            _cell(d.ai_conviction),
            _cell(d.agreed_with_ai),
            _cell(d.decision_price),
            _cell(d.recorded_at),
            _cell(d.snapshot_generated_at),
            _cell(d.note),
            _cell(d.outcome_price),
            _cell(d.outcome_at),
            _cell(d.outcome_return_pct),
            _cell(d.outcome_note),
            _cell(d.benchmark_symbol),
            _cell(d.benchmark_price),
            _cell(d.benchmark_outcome_price),
            _cell(d.benchmark_return_pct),
            _cell(d.excess_return_pct),
        ])
    return buf.getvalue()
