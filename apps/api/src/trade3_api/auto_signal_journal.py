import asyncio
import math
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .auto_signal_models import (
    AutoSignal,
    AutoSignalRequest,
    AutoSignalStats,
    AutoSymbolBreakdown,
)

SCHEMA_VERSION = 1
DIRECTIONAL = {"long", "short"}


class AutoSignalNotFoundError(LookupError):
    pass


def directional_return_pct(
    direction: str,
    decision_price: float | None,
    outcome_price: float,
) -> float | None:
    """Raw directional return from decision price to follow-up price, before costs.

    A short call profits when price falls, so its sign is inverted. A neutral
    call carries no position and therefore has no directional return.
    """

    if direction not in DIRECTIONAL or decision_price is None or decision_price <= 0:
        return None
    if outcome_price <= 0:
        return None
    raw = (outcome_price - decision_price) / decision_price
    return round(-raw if direction == "short" else raw, 6)


def benchmark_return_pct(
    price_at_decision: float | None,
    price_at_outcome: float | None,
) -> float | None:
    """Buy-and-hold benchmark return over the signal window (always long)."""

    if (
        price_at_decision is None
        or price_at_decision <= 0
        or price_at_outcome is None
        or price_at_outcome <= 0
    ):
        return None
    return round((price_at_outcome - price_at_decision) / price_at_decision, 6)


class AutoSignalJournal:
    def __init__(self, database_path: str) -> None:
        self._database_path = Path(database_path)
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def record(
        self,
        request: AutoSignalRequest,
        recorded_at: datetime,
    ) -> AutoSignal:
        async with self._lock:
            return await asyncio.to_thread(self._record_sync, request, recorded_at)

    async def due_unresolved(
        self,
        horizon_hours: float,
        now: datetime | None = None,
    ) -> list[AutoSignal]:
        moment = now or datetime.now(UTC)
        async with self._lock:
            return await asyncio.to_thread(self._due_unresolved_sync, horizon_hours, moment)

    async def resolve(
        self,
        signal_id: int,
        outcome_price: float,
        benchmark_outcome_price: float | None,
        resolved_at: datetime,
    ) -> AutoSignal:
        async with self._lock:
            return await asyncio.to_thread(
                self._resolve_sync, signal_id, outcome_price, benchmark_outcome_price, resolved_at
            )

    async def list_signals(self, limit: int = 100) -> list[AutoSignal]:
        async with self._lock:
            return await asyncio.to_thread(self._list_sync, limit)

    async def stats(
        self,
        horizon_hours: float = 8.0,
        scan_seconds: float = 1800.0,
        now: datetime | None = None,
    ) -> AutoSignalStats:
        moment = now or datetime.now(UTC)
        async with self._lock:
            return await asyncio.to_thread(self._stats_sync, horizon_hours, scan_seconds, moment)

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
                CREATE TABLE IF NOT EXISTS auto_signal_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auto_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    decision_price REAL,
                    generated_at TEXT,
                    recorded_at TEXT NOT NULL,
                    outcome_price REAL,
                    outcome_at TEXT,
                    forward_return_pct REAL,
                    benchmark_symbol TEXT,
                    benchmark_price REAL,
                    benchmark_outcome_price REAL,
                    benchmark_return_pct REAL,
                    excess_return_pct REAL
                );

                CREATE INDEX IF NOT EXISTS idx_auto_signals_recorded
                    ON auto_signals(recorded_at DESC);
                CREATE INDEX IF NOT EXISTS idx_auto_signals_open
                    ON auto_signals(outcome_at);
                """
            )
            connection.execute(
                """
                INSERT INTO auto_signal_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _record_sync(self, request: AutoSignalRequest, recorded_at: datetime) -> AutoSignal:
        row = {
            "symbol": request.symbol,
            "direction": request.direction,
            "decision_price": request.decision_price,
            "generated_at": _iso(request.generated_at) if request.generated_at else None,
            "recorded_at": _iso(recorded_at),
            "benchmark_symbol": request.benchmark_symbol,
            "benchmark_price": request.benchmark_price,
        }
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO auto_signals (
                    symbol, direction, decision_price, generated_at, recorded_at,
                    benchmark_symbol, benchmark_price
                ) VALUES (
                    :symbol, :direction, :decision_price, :generated_at, :recorded_at,
                    :benchmark_symbol, :benchmark_price
                )
                """,
                row,
            )
            signal_id = int(cursor.lastrowid or 0)
            stored = connection.execute(
                "SELECT * FROM auto_signals WHERE id = ?", (signal_id,)
            ).fetchone()
        return _row_to_signal(stored)

    def _due_unresolved_sync(self, horizon_hours: float, now: datetime) -> list[AutoSignal]:
        cutoff = _iso(now - timedelta(hours=horizon_hours))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM auto_signals
                WHERE outcome_at IS NULL AND recorded_at <= ?
                ORDER BY recorded_at
                """,
                (cutoff,),
            ).fetchall()
        return [_row_to_signal(row) for row in rows]

    def _resolve_sync(
        self,
        signal_id: int,
        outcome_price: float,
        benchmark_outcome_price: float | None,
        resolved_at: datetime,
    ) -> AutoSignal:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auto_signals WHERE id = ?", (signal_id,)
            ).fetchone()
            if row is None:
                raise AutoSignalNotFoundError(f"auto signal {signal_id} not found")
            return_pct = directional_return_pct(
                row["direction"], row["decision_price"], outcome_price
            )
            bench_pct = benchmark_return_pct(row["benchmark_price"], benchmark_outcome_price)
            excess = (
                round(return_pct - bench_pct, 6)
                if return_pct is not None and bench_pct is not None
                else None
            )
            connection.execute(
                """
                UPDATE auto_signals SET
                    outcome_price = :outcome_price,
                    outcome_at = :outcome_at,
                    forward_return_pct = :forward_return_pct,
                    benchmark_outcome_price = :benchmark_outcome_price,
                    benchmark_return_pct = :benchmark_return_pct,
                    excess_return_pct = :excess_return_pct
                WHERE id = :id
                """,
                {
                    "outcome_price": outcome_price,
                    "outcome_at": _iso(resolved_at),
                    "forward_return_pct": return_pct,
                    "benchmark_outcome_price": benchmark_outcome_price,
                    "benchmark_return_pct": bench_pct,
                    "excess_return_pct": excess,
                    "id": signal_id,
                },
            )
            updated = connection.execute(
                "SELECT * FROM auto_signals WHERE id = ?", (signal_id,)
            ).fetchone()
        return _row_to_signal(updated)

    def _list_sync(self, limit: int) -> list[AutoSignal]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM auto_signals ORDER BY recorded_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_signal(row) for row in rows]

    def _stats_sync(
        self,
        horizon_hours: float,
        scan_seconds: float,
        now: datetime,
    ) -> AutoSignalStats:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM auto_signals").fetchall()
        signals = [_row_to_signal(row) for row in rows]
        total = len(signals)
        horizon = timedelta(hours=horizon_hours)
        unresolved = [s for s in signals if s.outcome_at is None]
        due = sum(1 for s in unresolved if now - s.recorded_at >= horizon)
        directional = [s for s in signals if s.direction in DIRECTIONAL]
        resolved = [s for s in signals if s.forward_return_pct is not None]
        returns = [s.forward_return_pct for s in resolved if s.forward_return_pct is not None]
        wins = sum(value > 0 for value in returns)
        excess = [s.excess_return_pct for s in resolved if s.excess_return_pct is not None]
        beat = sum(value > 0 for value in excess)
        return AutoSignalStats(
            total=total,
            longs=sum(s.direction == "long" for s in signals),
            shorts=sum(s.direction == "short" for s in signals),
            neutrals=sum(s.direction not in DIRECTIONAL for s in signals),
            directional=len(directional),
            pending_resolution=len(unresolved),
            due_for_resolution=due,
            resolved=sum(s.outcome_at is not None for s in signals),
            directional_resolved=len(resolved),
            win_rate=round(wins / len(returns), 4) if returns else None,
            average_return_pct=round(sum(returns) / len(returns), 6) if returns else None,
            benchmark_resolved=len(excess),
            average_excess_return_pct=round(sum(excess) / len(excess), 6) if excess else None,
            beat_benchmark_rate=round(beat / len(excess), 4) if excess else None,
            coin_toss_z=_coin_toss_z(len(returns), wins),
            by_symbol=_symbol_breakdown(resolved),
            horizon_hours=horizon_hours,
            scan_seconds=scan_seconds,
        )


def _row_to_signal(row: sqlite3.Row) -> AutoSignal:
    return AutoSignal(
        id=row["id"],
        symbol=row["symbol"],
        direction=row["direction"],
        decision_price=row["decision_price"],
        generated_at=_optional_datetime(row["generated_at"]),
        recorded_at=_datetime(row["recorded_at"]),
        outcome_price=row["outcome_price"],
        outcome_at=_optional_datetime(row["outcome_at"]),
        forward_return_pct=row["forward_return_pct"],
        benchmark_symbol=row["benchmark_symbol"],
        benchmark_price=row["benchmark_price"],
        benchmark_outcome_price=row["benchmark_outcome_price"],
        benchmark_return_pct=row["benchmark_return_pct"],
        excess_return_pct=row["excess_return_pct"],
    )


def _coin_toss_z(n: int, wins: int) -> float | None:
    """Z-score of the directional win count against a fair-coin 50% baseline."""

    if n <= 0:
        return None
    return round((wins - n * 0.5) / math.sqrt(n * 0.25), 4)


def _symbol_breakdown(resolved: list[AutoSignal]) -> list[AutoSymbolBreakdown]:
    by_symbol: dict[str, list[AutoSignal]] = {}
    for signal in resolved:
        by_symbol.setdefault(signal.symbol, []).append(signal)
    rows: list[AutoSymbolBreakdown] = []
    for symbol, items in sorted(by_symbol.items()):
        returns = [s.forward_return_pct for s in items if s.forward_return_pct is not None]
        excess = [s.excess_return_pct for s in items if s.excess_return_pct is not None]
        wins = sum(value > 0 for value in returns)
        rows.append(
            AutoSymbolBreakdown(
                symbol=symbol,
                resolved=len(items),
                win_rate=round(wins / len(returns), 4) if returns else None,
                average_return_pct=round(sum(returns) / len(returns), 6) if returns else None,
                average_excess_return_pct=(
                    round(sum(excess) / len(excess), 6) if excess else None
                ),
            )
        )
    return rows


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
