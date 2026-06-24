import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .carry_test_models import (
    CarryPosition,
    CarryPositionRequest,
    CarryTestStats,
)

SCHEMA_VERSION = 1
HOURS_PER_YEAR = 24 * 365


class CarryPositionNotFoundError(LookupError):
    pass


def realized_carry_pct(side: str, funding_sum_fraction: float) -> float:
    """Funding collected over the window, in percent, signed by the held side.

    A short-perp position receives positive funding; a long-perp position
    receives negative funding. Summing the realized rates captures persistence —
    if funding flipped during the window, the position paid it back.
    """

    sign = 1.0 if side == "short_perp_long_spot" else -1.0
    return round(sign * funding_sum_fraction * 100, 6)


def annualize_pct(value_pct: float, elapsed_hours: float) -> float:
    if elapsed_hours <= 0:
        return 0.0
    return round(value_pct / elapsed_hours * HOURS_PER_YEAR, 4)


class CarryTestJournal:
    def __init__(self, database_path: str) -> None:
        self._database_path = Path(database_path)
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def record(
        self, request: CarryPositionRequest, opened_at: datetime
    ) -> CarryPosition:
        async with self._lock:
            return await asyncio.to_thread(self._record_sync, request, opened_at)

    async def due_unresolved(
        self, horizon_hours: float, now: datetime | None = None
    ) -> list[CarryPosition]:
        moment = now or datetime.now(UTC)
        async with self._lock:
            return await asyncio.to_thread(self._due_unresolved_sync, horizon_hours, moment)

    async def resolve(
        self,
        position_id: int,
        realized_funding_pct: float,
        funding_events: int,
        resolved_at: datetime,
    ) -> CarryPosition:
        async with self._lock:
            return await asyncio.to_thread(
                self._resolve_sync,
                position_id,
                realized_funding_pct,
                funding_events,
                resolved_at,
            )

    async def list_positions(self, limit: int = 100) -> list[CarryPosition]:
        async with self._lock:
            return await asyncio.to_thread(self._list_sync, limit)

    async def stats(
        self,
        horizon_hours: float = 48.0,
        scan_seconds: float = 28800.0,
        now: datetime | None = None,
    ) -> CarryTestStats:
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
                CREATE TABLE IF NOT EXISTS carry_test_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS carry_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_funding_rate_pct REAL NOT NULL,
                    entry_apr_pct REAL NOT NULL,
                    funding_interval_hours REAL NOT NULL,
                    round_trip_fee_pct REAL NOT NULL,
                    opened_at TEXT NOT NULL,
                    resolved_at TEXT,
                    realized_funding_pct REAL,
                    net_carry_pct REAL,
                    annualized_net_apr_pct REAL,
                    funding_events INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_carry_positions_open
                    ON carry_positions(resolved_at);
                """
            )
            connection.execute(
                """
                INSERT INTO carry_test_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _record_sync(
        self, request: CarryPositionRequest, opened_at: datetime
    ) -> CarryPosition:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO carry_positions (
                    symbol, side, entry_funding_rate_pct, entry_apr_pct,
                    funding_interval_hours, round_trip_fee_pct, opened_at
                ) VALUES (
                    :symbol, :side, :entry_funding_rate_pct, :entry_apr_pct,
                    :funding_interval_hours, :round_trip_fee_pct, :opened_at
                )
                """,
                {
                    "symbol": request.symbol,
                    "side": request.side,
                    "entry_funding_rate_pct": request.entry_funding_rate_pct,
                    "entry_apr_pct": request.entry_apr_pct,
                    "funding_interval_hours": request.funding_interval_hours,
                    "round_trip_fee_pct": request.round_trip_fee_pct,
                    "opened_at": _iso(opened_at),
                },
            )
            position_id = int(cursor.lastrowid or 0)
            stored = connection.execute(
                "SELECT * FROM carry_positions WHERE id = ?", (position_id,)
            ).fetchone()
        return _row_to_position(stored)

    def _due_unresolved_sync(
        self, horizon_hours: float, now: datetime
    ) -> list[CarryPosition]:
        cutoff = _iso(now - timedelta(hours=horizon_hours))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM carry_positions
                WHERE resolved_at IS NULL AND opened_at <= ?
                ORDER BY opened_at
                """,
                (cutoff,),
            ).fetchall()
        return [_row_to_position(row) for row in rows]

    def _resolve_sync(
        self,
        position_id: int,
        realized_funding_pct: float,
        funding_events: int,
        resolved_at: datetime,
    ) -> CarryPosition:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM carry_positions WHERE id = ?", (position_id,)
            ).fetchone()
            if row is None:
                raise CarryPositionNotFoundError(f"carry position {position_id} not found")
            opened_at = _datetime(row["opened_at"])
            elapsed_hours = (resolved_at - opened_at).total_seconds() / 3600
            net_carry_pct = round(realized_funding_pct - row["round_trip_fee_pct"], 6)
            annualized = annualize_pct(net_carry_pct, elapsed_hours)
            connection.execute(
                """
                UPDATE carry_positions SET
                    resolved_at = :resolved_at,
                    realized_funding_pct = :realized_funding_pct,
                    net_carry_pct = :net_carry_pct,
                    annualized_net_apr_pct = :annualized_net_apr_pct,
                    funding_events = :funding_events
                WHERE id = :id
                """,
                {
                    "resolved_at": _iso(resolved_at),
                    "realized_funding_pct": realized_funding_pct,
                    "net_carry_pct": net_carry_pct,
                    "annualized_net_apr_pct": annualized,
                    "funding_events": funding_events,
                    "id": position_id,
                },
            )
            updated = connection.execute(
                "SELECT * FROM carry_positions WHERE id = ?", (position_id,)
            ).fetchone()
        return _row_to_position(updated)

    def _list_sync(self, limit: int) -> list[CarryPosition]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM carry_positions ORDER BY opened_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_position(row) for row in rows]

    def _stats_sync(
        self, horizon_hours: float, scan_seconds: float, now: datetime
    ) -> CarryTestStats:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM carry_positions").fetchall()
        positions = [_row_to_position(row) for row in rows]
        total = len(positions)
        horizon = timedelta(hours=horizon_hours)
        unresolved = [p for p in positions if p.resolved_at is None]
        due = sum(1 for p in unresolved if now - p.opened_at >= horizon)
        resolved = [p for p in positions if p.net_carry_pct is not None]
        net = [p.net_carry_pct for p in resolved if p.net_carry_pct is not None]
        realized = [
            p.realized_funding_pct for p in resolved if p.realized_funding_pct is not None
        ]
        aprs = [
            p.annualized_net_apr_pct
            for p in resolved
            if p.annualized_net_apr_pct is not None
        ]
        positive = sum(value > 0 for value in net)
        return CarryTestStats(
            total=total,
            open_positions=len(unresolved),
            resolved=len(resolved),
            due_for_resolution=due,
            win_rate_after_fees=round(positive / len(net), 4) if net else None,
            positive_after_fees=positive,
            mean_realized_funding_pct=(
                round(sum(realized) / len(realized), 6) if realized else None
            ),
            mean_net_carry_pct=round(sum(net) / len(net), 6) if net else None,
            mean_annualized_net_apr_pct=round(sum(aprs) / len(aprs), 4) if aprs else None,
            horizon_hours=horizon_hours,
            scan_seconds=scan_seconds,
        )


def _row_to_position(row: sqlite3.Row) -> CarryPosition:
    return CarryPosition(
        id=row["id"],
        symbol=row["symbol"],
        side=row["side"],
        entry_funding_rate_pct=row["entry_funding_rate_pct"],
        entry_apr_pct=row["entry_apr_pct"],
        funding_interval_hours=row["funding_interval_hours"],
        round_trip_fee_pct=row["round_trip_fee_pct"],
        opened_at=_datetime(row["opened_at"]),
        resolved_at=_optional_datetime(row["resolved_at"]),
        realized_funding_pct=row["realized_funding_pct"],
        net_carry_pct=row["net_carry_pct"],
        annualized_net_apr_pct=row["annualized_net_apr_pct"],
        funding_events=row["funding_events"],
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
