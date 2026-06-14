import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .journal_evaluation import evaluate_signal_row
from .journal_models import JournalSignal, JournalStats, TargetHit
from .live_models import IntradayCandidate, TradeTarget
from .market_models import Candle

SCHEMA_VERSION = 2
EXECUTION_POLICY = "tp1_or_stop_all_out_v1"
RECORDABLE_PLAN_STATES = {"waiting_entry", "ready", "missed"}
OPEN_LIFECYCLE_STATES = {"pending_entry", "active"}


class SignalJournal:
    def __init__(
        self,
        database_path: str,
        pending_expiry_hours: float = 6,
        active_expiry_hours: float = 24,
        taker_fee_rate_pct: float = 0.055,
        slippage_bps: float = 2,
        minimum_sample_size: int = 100,
    ) -> None:
        self._database_path = Path(database_path)
        self._pending_expiry = timedelta(hours=pending_expiry_hours)
        self._active_expiry = timedelta(hours=active_expiry_hours)
        self._taker_fee_rate_pct = taker_fee_rate_pct
        self._slippage_bps = slippage_bps
        self._minimum_sample_size = minimum_sample_size
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def record_candidates(
        self,
        candidates: list[IntradayCandidate],
        recorded_at: datetime,
    ) -> int:
        rows = [
            row
            for candidate in candidates
            if (
                row := _candidate_row(
                    candidate,
                    recorded_at,
                    self._taker_fee_rate_pct,
                    self._slippage_bps,
                )
            )
            is not None
        ]
        if not rows:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._insert_rows_sync, rows)

    async def evaluate(
        self,
        candles_by_symbol: dict[str, list[Candle]],
        now: datetime,
    ) -> int:
        async with self._lock:
            return await asyncio.to_thread(
                self._evaluate_sync,
                candles_by_symbol,
                now,
            )

    async def open_symbols(self) -> list[str]:
        async with self._lock:
            return await asyncio.to_thread(self._open_symbols_sync)

    async def unresolved_execution_symbols(self) -> list[str]:
        async with self._lock:
            return await asyncio.to_thread(self._unresolved_execution_symbols_sync)

    async def list_signals(
        self,
        limit: int = 100,
        lifecycle_state: str | None = None,
    ) -> list[JournalSignal]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_signals_sync,
                limit,
                lifecycle_state,
            )

    async def stats(self) -> JournalStats:
        async with self._lock:
            return await asyncio.to_thread(self._stats_sync)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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
                CREATE TABLE IF NOT EXISTS journal_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    setup_type TEXT NOT NULL,
                    plan_status TEXT NOT NULL,
                    lifecycle_state TEXT NOT NULL,
                    outcome TEXT,
                    score REAL NOT NULL,
                    signal_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    entered_at TEXT,
                    closed_at TEXT,
                    entry_lower REAL NOT NULL,
                    entry_upper REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_price REAL NOT NULL,
                    structural_reward_risk REAL,
                    targets_json TEXT NOT NULL,
                    target_hits_json TEXT NOT NULL DEFAULT '[]',
                    mfe_r REAL NOT NULL DEFAULT 0,
                    mae_r REAL NOT NULL DEFAULT 0,
                    result_r REAL,
                    last_evaluated_at TEXT,
                    snapshot_json TEXT NOT NULL,
                    execution_policy TEXT NOT NULL DEFAULT 'tp1_or_stop_all_out_v1',
                    taker_fee_rate_pct REAL NOT NULL DEFAULT 0.055,
                    slippage_bps REAL NOT NULL DEFAULT 2,
                    exit_reference_price REAL,
                    entry_fill_price REAL,
                    exit_fill_price REAL,
                    fee_cost_r REAL,
                    slippage_cost_r REAL,
                    net_result_r REAL
                );

                CREATE INDEX IF NOT EXISTS idx_signals_state
                    ON signals(lifecycle_state);
                CREATE INDEX IF NOT EXISTS idx_signals_symbol_time
                    ON signals(symbol, signal_at DESC);
                """
            )
            _migrate_signal_columns(connection)
            connection.execute(
                """
                INSERT INTO journal_meta(key, value) VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _insert_rows_sync(self, rows: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._connect() as connection:
            for row in rows:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO signals (
                        fingerprint, symbol, direction, setup_type, plan_status,
                        lifecycle_state, outcome, score, signal_at, recorded_at,
                        closed_at, entry_lower, entry_upper, entry_price, stop_price,
                        structural_reward_risk, targets_json, snapshot_json,
                        execution_policy, taker_fee_rate_pct, slippage_bps
                    ) VALUES (
                        :fingerprint, :symbol, :direction, :setup_type, :plan_status,
                        :lifecycle_state, :outcome, :score, :signal_at, :recorded_at,
                        :closed_at, :entry_lower, :entry_upper, :entry_price, :stop_price,
                        :structural_reward_risk, :targets_json, :snapshot_json,
                        :execution_policy, :taker_fee_rate_pct, :slippage_bps
                    )
                    """,
                    row,
                )
                inserted += cursor.rowcount
        return inserted

    def _evaluate_sync(
        self,
        candles_by_symbol: dict[str, list[Candle]],
        now: datetime,
    ) -> int:
        updates = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM signals
                WHERE lifecycle_state IN ('pending_entry', 'active')
                ORDER BY signal_at
                """
            ).fetchall()
            for row in rows:
                candles = candles_by_symbol.get(row["symbol"], [])
                update = evaluate_signal_row(
                    row,
                    candles,
                    now,
                    self._pending_expiry,
                    self._active_expiry,
                )
                if update is None:
                    continue
                connection.execute(
                    """
                    UPDATE signals SET
                        lifecycle_state = :lifecycle_state,
                        outcome = :outcome,
                        entered_at = :entered_at,
                        closed_at = :closed_at,
                        target_hits_json = :target_hits_json,
                        mfe_r = :mfe_r,
                        mae_r = :mae_r,
                        result_r = :result_r,
                        exit_reference_price = :exit_reference_price,
                        entry_fill_price = :entry_fill_price,
                        exit_fill_price = :exit_fill_price,
                        fee_cost_r = :fee_cost_r,
                        slippage_cost_r = :slippage_cost_r,
                        net_result_r = :net_result_r,
                        last_evaluated_at = :last_evaluated_at
                    WHERE id = :id
                    """,
                    update,
                )
                updates += 1
        return updates

    def _open_symbols_sync(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT symbol FROM signals
                WHERE lifecycle_state IN ('pending_entry', 'active')
                ORDER BY symbol
                """
            ).fetchall()
        return [row["symbol"] for row in rows]

    def _unresolved_execution_symbols_sync(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT symbol FROM signals
                WHERE lifecycle_state IN ('pending_entry', 'active')
                    AND net_result_r IS NULL
                ORDER BY symbol
                """
            ).fetchall()
        return [row["symbol"] for row in rows]

    def _list_signals_sync(
        self,
        limit: int,
        lifecycle_state: str | None,
    ) -> list[JournalSignal]:
        query = "SELECT * FROM signals"
        params: list[Any] = []
        if lifecycle_state:
            query += " WHERE lifecycle_state = ?"
            params.append(lifecycle_state)
        query += " ORDER BY signal_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_signal(row) for row in rows]

    def _stats_sync(self) -> JournalStats:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM signals").fetchall()
        signals = [_row_to_signal(row) for row in rows]
        entered = [signal for signal in signals if signal.entered_at is not None]
        resolved_entered = [
            signal
            for signal in entered
            if signal.lifecycle_state == "closed" and signal.outcome != "ambiguous"
        ]
        resolved_trades = sorted(
            (signal for signal in signals if signal.net_result_r is not None),
            key=lambda signal: (signal.signal_at, signal.id),
        )
        net_results = [
            signal.net_result_r for signal in resolved_trades if signal.net_result_r is not None
        ]
        wins = [result for result in net_results if result > 0]
        losses = [result for result in net_results if result < 0]
        breakeven = [result for result in net_results if result == 0]
        return JournalStats(
            total_signals=len(signals),
            pending_entry=sum(signal.lifecycle_state == "pending_entry" for signal in signals),
            active=sum(signal.lifecycle_state == "active" for signal in signals),
            closed=sum(signal.lifecycle_state == "closed" for signal in signals),
            entered=len(entered),
            ambiguous=sum(signal.outcome == "ambiguous" for signal in signals),
            expired_without_entry=sum(
                signal.outcome == "expired_without_entry" for signal in signals
            ),
            missed_at_recording=sum(signal.outcome == "missed_at_recording" for signal in signals),
            stop_before_target=sum(signal.outcome == "stop_before_target" for signal in signals),
            stop_after_target=sum(signal.outcome == "stop_after_target" for signal in signals),
            tp1_hits=_target_hit_count(signals, "TP1"),
            tp2_hits=_target_hit_count(signals, "TP2"),
            structure_hits=_target_hit_count(signals, "STRUCTURE"),
            tp1_hit_rate=(
                round(_target_hit_count(resolved_entered, "TP1") / len(resolved_entered), 4)
                if resolved_entered
                else None
            ),
            average_mfe_r=_average([signal.mfe_r for signal in entered]),
            average_mae_r=_average([signal.mae_r for signal in entered]),
            execution_policy=EXECUTION_POLICY,
            taker_fee_rate_pct=self._taker_fee_rate_pct,
            slippage_bps=self._slippage_bps,
            resolved_trades=len(net_results),
            net_wins=len(wins),
            net_losses=len(losses),
            net_breakeven=len(breakeven),
            net_win_rate=round(len(wins) / len(net_results), 4) if net_results else None,
            expectancy_r=_average(net_results),
            profit_factor=(round(sum(wins) / abs(sum(losses)), 4) if wins and losses else None),
            cumulative_net_r=round(sum(net_results), 4) if net_results else None,
            max_drawdown_r=_max_drawdown(net_results),
            average_fee_cost_r=_average(
                [signal.fee_cost_r for signal in resolved_trades if signal.fee_cost_r is not None]
            ),
            average_slippage_cost_r=_average(
                [
                    signal.slippage_cost_r
                    for signal in resolved_trades
                    if signal.slippage_cost_r is not None
                ]
            ),
            minimum_sample_size=self._minimum_sample_size,
            sample_sufficient=len(net_results) >= self._minimum_sample_size,
        )


def _candidate_row(
    candidate: IntradayCandidate,
    recorded_at: datetime,
    taker_fee_rate_pct: float,
    slippage_bps: float,
) -> dict[str, Any] | None:
    plan = candidate.trade_plan
    if plan is None or plan.confirmation_at is None or plan.status not in RECORDABLE_PLAN_STATES:
        return None
    signal_at = plan.confirmation_at + timedelta(minutes=5)
    fingerprint_source = (
        f"{candidate.symbol}|{candidate.direction}|{plan.setup_type}|"
        f"{plan.confirmation_at.isoformat()}"
    )
    fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    entry_price = plan.entry_zone.upper if candidate.direction == "long" else plan.entry_zone.lower
    missed = plan.status == "missed"
    return {
        "fingerprint": fingerprint,
        "symbol": candidate.symbol,
        "direction": candidate.direction,
        "setup_type": plan.setup_type,
        "plan_status": plan.status,
        "lifecycle_state": "closed" if missed else "pending_entry",
        "outcome": "missed_at_recording" if missed else None,
        "score": candidate.score,
        "signal_at": _iso(signal_at),
        "recorded_at": _iso(recorded_at),
        "closed_at": _iso(recorded_at) if missed else None,
        "entry_lower": plan.entry_zone.lower,
        "entry_upper": plan.entry_zone.upper,
        "entry_price": entry_price,
        "stop_price": plan.invalidation_price,
        "structural_reward_risk": plan.structural_reward_risk,
        "targets_json": json.dumps(
            [target.model_dump(mode="json") for target in plan.targets],
            separators=(",", ":"),
        ),
        "snapshot_json": candidate.model_dump_json(),
        "execution_policy": EXECUTION_POLICY,
        "taker_fee_rate_pct": taker_fee_rate_pct,
        "slippage_bps": slippage_bps,
    }


def _row_to_signal(row: sqlite3.Row) -> JournalSignal:
    return JournalSignal(
        id=row["id"],
        fingerprint=row["fingerprint"],
        symbol=row["symbol"],
        direction=row["direction"],
        setup_type=row["setup_type"],
        plan_status=row["plan_status"],
        lifecycle_state=row["lifecycle_state"],
        outcome=row["outcome"],
        score=row["score"],
        signal_at=_datetime(row["signal_at"]),
        recorded_at=_datetime(row["recorded_at"]),
        entered_at=_optional_datetime(row["entered_at"]),
        closed_at=_optional_datetime(row["closed_at"]),
        entry_lower=row["entry_lower"],
        entry_upper=row["entry_upper"],
        entry_price=row["entry_price"],
        stop_price=row["stop_price"],
        structural_reward_risk=row["structural_reward_risk"],
        targets=[TradeTarget.model_validate(item) for item in json.loads(row["targets_json"])],
        target_hits=[
            TargetHit.model_validate(item) for item in json.loads(row["target_hits_json"])
        ],
        mfe_r=row["mfe_r"],
        mae_r=row["mae_r"],
        result_r=row["result_r"],
        execution_policy=row["execution_policy"],
        taker_fee_rate_pct=row["taker_fee_rate_pct"],
        slippage_bps=row["slippage_bps"],
        exit_reference_price=row["exit_reference_price"],
        entry_fill_price=row["entry_fill_price"],
        exit_fill_price=row["exit_fill_price"],
        fee_cost_r=row["fee_cost_r"],
        slippage_cost_r=row["slippage_cost_r"],
        net_result_r=row["net_result_r"],
        last_evaluated_at=_optional_datetime(row["last_evaluated_at"]),
    )


def _target_hit_count(signals: list[JournalSignal], label: str) -> int:
    return sum(any(hit.label == label for hit in signal.target_hits) for signal in signals)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _max_drawdown(results: list[float]) -> float | None:
    if not results:
        return None
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for result in results:
        equity += result
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 4)


def _migrate_signal_columns(connection: sqlite3.Connection) -> None:
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(signals)").fetchall()}
    columns = {
        "execution_policy": "TEXT NOT NULL DEFAULT 'tp1_or_stop_all_out_v1'",
        "taker_fee_rate_pct": "REAL NOT NULL DEFAULT 0.055",
        "slippage_bps": "REAL NOT NULL DEFAULT 2",
        "exit_reference_price": "REAL",
        "entry_fill_price": "REAL",
        "exit_fill_price": "REAL",
        "fee_cost_r": "REAL",
        "slippage_cost_r": "REAL",
        "net_result_r": "REAL",
    }
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE signals ADD COLUMN {name} {definition}")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _optional_datetime(value: str | None) -> datetime | None:
    return _datetime(value) if value else None
