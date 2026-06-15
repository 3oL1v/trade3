import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .decision_models import (
    DecisionAction,
    DecisionDirection,
    DecisionOutcomeRequest,
    ManualDecision,
    ManualDecisionRequest,
    ManualDecisionStats,
)

SCHEMA_VERSION = 3
DEFAULT_BENCHMARK_SYMBOL = "BTCUSDT"


class DecisionNotFoundError(LookupError):
    pass


def benchmark_return_pct(
    price_at_decision: float | None,
    price_at_outcome: float | None,
) -> float | None:
    """Buy-and-hold benchmark return over the decision window (always long)."""

    if (
        price_at_decision is None
        or price_at_decision <= 0
        or price_at_outcome is None
        or price_at_outcome <= 0
    ):
        return None
    return round((price_at_outcome - price_at_decision) / price_at_decision, 6)


def forward_return_pct(
    direction: DecisionDirection,
    decision_price: float | None,
    outcome_price: float,
) -> float | None:
    """Directional return from decision price to follow-up price, before costs.

    A short call profits when price falls, so its sign is inverted. Reject and
    defer carry no position; the raw upward move is recorded as context only.
    """

    if decision_price is None or decision_price <= 0 or outcome_price <= 0:
        return None
    raw = (outcome_price - decision_price) / decision_price
    if direction == DecisionDirection.SHORT:
        return round(-raw, 6)
    return round(raw, 6)


def agreement_with_ai(
    action: DecisionAction,
    direction: DecisionDirection,
    ai_verdict: str | None,
) -> bool | None:
    """Whether the user's call lines up with the AI verdict shown at the time.

    Returns None when no AI verdict was present, so rubber-stamping and
    independent judgement can be told apart later.
    """

    if not ai_verdict:
        return None
    if action == DecisionAction.ACCEPT:
        if direction == DecisionDirection.LONG:
            return ai_verdict == "long_candidate"
        if direction == DecisionDirection.SHORT:
            return ai_verdict == "short_candidate"
        return False
    return ai_verdict == "wait"


class ManualDecisionJournal:
    def __init__(self, database_path: str) -> None:
        self._database_path = Path(database_path)
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def record(
        self,
        request: ManualDecisionRequest,
        recorded_at: datetime,
        benchmark_symbol: str | None = None,
        benchmark_price: float | None = None,
    ) -> ManualDecision:
        async with self._lock:
            return await asyncio.to_thread(
                self._record_sync, request, recorded_at, benchmark_symbol, benchmark_price
            )

    async def resolve(
        self,
        decision_id: int,
        outcome: DecisionOutcomeRequest,
        resolved_at: datetime,
        benchmark_price: float | None = None,
    ) -> ManualDecision:
        async with self._lock:
            return await asyncio.to_thread(
                self._resolve_sync, decision_id, outcome, resolved_at, benchmark_price
            )

    async def list_decisions(
        self,
        limit: int = 100,
        action: str | None = None,
    ) -> list[ManualDecision]:
        async with self._lock:
            return await asyncio.to_thread(self._list_sync, limit, action)

    async def stats(self) -> ManualDecisionStats:
        async with self._lock:
            return await asyncio.to_thread(self._stats_sync)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS manual_decision_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS manual_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    ai_verdict TEXT,
                    ai_conviction TEXT,
                    agreed_with_ai INTEGER,
                    decision_price REAL,
                    snapshot_generated_at TEXT,
                    recorded_at TEXT NOT NULL,
                    note TEXT,
                    outcome_price REAL,
                    outcome_at TEXT,
                    outcome_return_pct REAL,
                    outcome_note TEXT,
                    benchmark_symbol TEXT,
                    benchmark_price REAL,
                    benchmark_outcome_price REAL,
                    benchmark_return_pct REAL,
                    excess_return_pct REAL,
                    analysis_snapshot_json TEXT,
                    ai_review_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_manual_decisions_recorded
                    ON manual_decisions(recorded_at DESC);
                """
            )
            _migrate_columns(connection)
            connection.execute(
                """
                INSERT INTO manual_decision_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _record_sync(
        self,
        request: ManualDecisionRequest,
        recorded_at: datetime,
        benchmark_symbol: str | None,
        benchmark_price: float | None,
    ) -> ManualDecision:
        agreed = agreement_with_ai(request.action, request.direction, request.ai_verdict)
        row = {
            "symbol": request.symbol,
            "action": request.action.value,
            "direction": request.direction.value,
            "ai_verdict": request.ai_verdict,
            "ai_conviction": request.ai_conviction,
            "agreed_with_ai": None if agreed is None else int(agreed),
            "decision_price": request.decision_price,
            "snapshot_generated_at": (
                _iso(request.snapshot_generated_at) if request.snapshot_generated_at else None
            ),
            "recorded_at": _iso(recorded_at),
            "note": request.note,
            "benchmark_symbol": benchmark_symbol,
            "benchmark_price": benchmark_price,
            "analysis_snapshot_json": _dump(request.analysis_snapshot),
            "ai_review_json": _dump(request.ai_review),
        }
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO manual_decisions (
                    symbol, action, direction, ai_verdict, ai_conviction,
                    agreed_with_ai, decision_price, snapshot_generated_at, recorded_at, note,
                    benchmark_symbol, benchmark_price, analysis_snapshot_json, ai_review_json
                ) VALUES (
                    :symbol, :action, :direction, :ai_verdict, :ai_conviction,
                    :agreed_with_ai, :decision_price, :snapshot_generated_at, :recorded_at, :note,
                    :benchmark_symbol, :benchmark_price, :analysis_snapshot_json, :ai_review_json
                )
                """,
                row,
            )
            decision_id = int(cursor.lastrowid or 0)
            stored = connection.execute(
                "SELECT * FROM manual_decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return _row_to_decision(stored)

    def _resolve_sync(
        self,
        decision_id: int,
        outcome: DecisionOutcomeRequest,
        resolved_at: datetime,
        benchmark_price: float | None,
    ) -> ManualDecision:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM manual_decisions WHERE id = ?", (decision_id,)
            ).fetchone()
            if row is None:
                raise DecisionNotFoundError(f"decision {decision_id} not found")
            direction = DecisionDirection(row["direction"])
            return_pct = forward_return_pct(direction, row["decision_price"], outcome.price)
            bench_pct = benchmark_return_pct(row["benchmark_price"], benchmark_price)
            excess = (
                round(return_pct - bench_pct, 6)
                if return_pct is not None and bench_pct is not None
                else None
            )
            connection.execute(
                """
                UPDATE manual_decisions SET
                    outcome_price = :outcome_price,
                    outcome_at = :outcome_at,
                    outcome_return_pct = :outcome_return_pct,
                    outcome_note = :outcome_note,
                    benchmark_outcome_price = :benchmark_outcome_price,
                    benchmark_return_pct = :benchmark_return_pct,
                    excess_return_pct = :excess_return_pct
                WHERE id = :id
                """,
                {
                    "outcome_price": outcome.price,
                    "outcome_at": _iso(resolved_at),
                    "outcome_return_pct": return_pct,
                    "outcome_note": outcome.note,
                    "benchmark_outcome_price": benchmark_price,
                    "benchmark_return_pct": bench_pct,
                    "excess_return_pct": excess,
                    "id": decision_id,
                },
            )
            updated = connection.execute(
                "SELECT * FROM manual_decisions WHERE id = ?", (decision_id,)
            ).fetchone()
        return _row_to_decision(updated)

    def _list_sync(self, limit: int, action: str | None) -> list[ManualDecision]:
        query = "SELECT * FROM manual_decisions"
        params: list[Any] = []
        if action:
            query += " WHERE action = ?"
            params.append(action)
        query += " ORDER BY recorded_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_decision(row) for row in rows]

    def _stats_sync(self) -> ManualDecisionStats:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM manual_decisions").fetchall()
        decisions = [_row_to_decision(row) for row in rows]
        total = len(decisions)
        accepts = [d for d in decisions if d.action == DecisionAction.ACCEPT]
        comparable = [d for d in decisions if d.agreed_with_ai is not None]
        agreed = sum(d.agreed_with_ai is True for d in comparable)
        resolved = [d for d in decisions if d.outcome_return_pct is not None]
        accepts_resolved = [
            d for d in accepts if d.outcome_return_pct is not None
        ]
        accept_returns = [d.outcome_return_pct for d in accepts_resolved]
        accept_wins = sum(value > 0 for value in accept_returns)
        accept_excess = [
            d.excess_return_pct for d in accepts_resolved if d.excess_return_pct is not None
        ]
        beat = sum(value > 0 for value in accept_excess)
        return ManualDecisionStats(
            total=total,
            accepted=len(accepts),
            rejected=sum(d.action == DecisionAction.REJECT for d in decisions),
            deferred=sum(d.action == DecisionAction.DEFER for d in decisions),
            longs=sum(d.direction == DecisionDirection.LONG for d in decisions),
            shorts=sum(d.direction == DecisionDirection.SHORT for d in decisions),
            accept_rate=round(len(accepts) / total, 4) if total else None,
            ai_comparable=len(comparable),
            agreed_with_ai=agreed,
            agreement_rate=round(agreed / len(comparable), 4) if comparable else None,
            resolved=len(resolved),
            accepts_resolved=len(accepts_resolved),
            accept_win_rate=(
                round(accept_wins / len(accepts_resolved), 4) if accepts_resolved else None
            ),
            average_accept_return_pct=(
                round(sum(accept_returns) / len(accept_returns), 6) if accept_returns else None
            ),
            benchmark_resolved=len(accept_excess),
            average_excess_return_pct=(
                round(sum(accept_excess) / len(accept_excess), 6) if accept_excess else None
            ),
            beat_benchmark_rate=(
                round(beat / len(accept_excess), 4) if accept_excess else None
            ),
        )


def _row_to_decision(row: sqlite3.Row) -> ManualDecision:
    agreed = row["agreed_with_ai"]
    return ManualDecision(
        id=row["id"],
        symbol=row["symbol"],
        action=DecisionAction(row["action"]),
        direction=DecisionDirection(row["direction"]),
        ai_verdict=row["ai_verdict"],
        ai_conviction=row["ai_conviction"],
        agreed_with_ai=None if agreed is None else bool(agreed),
        decision_price=row["decision_price"],
        snapshot_generated_at=_optional_datetime(row["snapshot_generated_at"]),
        recorded_at=_datetime(row["recorded_at"]),
        note=row["note"],
        outcome_price=row["outcome_price"],
        outcome_at=_optional_datetime(row["outcome_at"]),
        outcome_return_pct=row["outcome_return_pct"],
        outcome_note=row["outcome_note"],
        benchmark_symbol=row["benchmark_symbol"],
        benchmark_price=row["benchmark_price"],
        benchmark_outcome_price=row["benchmark_outcome_price"],
        benchmark_return_pct=row["benchmark_return_pct"],
        excess_return_pct=row["excess_return_pct"],
        analysis_snapshot=_load(row["analysis_snapshot_json"]),
        ai_review=_load(row["ai_review_json"]),
    )


def _migrate_columns(connection: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(manual_decisions)").fetchall()
    }
    columns = {
        "decision_price": "REAL",
        "outcome_price": "REAL",
        "outcome_at": "TEXT",
        "outcome_return_pct": "REAL",
        "outcome_note": "TEXT",
        "benchmark_symbol": "TEXT",
        "benchmark_price": "REAL",
        "benchmark_outcome_price": "REAL",
        "benchmark_return_pct": "REAL",
        "excess_return_pct": "REAL",
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(
                f"ALTER TABLE manual_decisions ADD COLUMN {name} {definition}"
            )


def _dump(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value, separators=(",", ":")) if value is not None else None


def _load(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
