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
    ManualDecision,
    ManualDecisionRequest,
    ManualDecisionStats,
)

SCHEMA_VERSION = 1


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
    ) -> ManualDecision:
        async with self._lock:
            return await asyncio.to_thread(self._record_sync, request, recorded_at)

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
                    snapshot_generated_at TEXT,
                    recorded_at TEXT NOT NULL,
                    note TEXT,
                    analysis_snapshot_json TEXT,
                    ai_review_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_manual_decisions_recorded
                    ON manual_decisions(recorded_at DESC);
                """
            )
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
    ) -> ManualDecision:
        agreed = agreement_with_ai(request.action, request.direction, request.ai_verdict)
        row = {
            "symbol": request.symbol,
            "action": request.action.value,
            "direction": request.direction.value,
            "ai_verdict": request.ai_verdict,
            "ai_conviction": request.ai_conviction,
            "agreed_with_ai": None if agreed is None else int(agreed),
            "snapshot_generated_at": (
                _iso(request.snapshot_generated_at) if request.snapshot_generated_at else None
            ),
            "recorded_at": _iso(recorded_at),
            "note": request.note,
            "analysis_snapshot_json": _dump(request.analysis_snapshot),
            "ai_review_json": _dump(request.ai_review),
        }
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO manual_decisions (
                    symbol, action, direction, ai_verdict, ai_conviction,
                    agreed_with_ai, snapshot_generated_at, recorded_at, note,
                    analysis_snapshot_json, ai_review_json
                ) VALUES (
                    :symbol, :action, :direction, :ai_verdict, :ai_conviction,
                    :agreed_with_ai, :snapshot_generated_at, :recorded_at, :note,
                    :analysis_snapshot_json, :ai_review_json
                )
                """,
                row,
            )
            decision_id = int(cursor.lastrowid or 0)
        return ManualDecision(
            id=decision_id,
            symbol=request.symbol,
            action=request.action,
            direction=request.direction,
            ai_verdict=request.ai_verdict,
            ai_conviction=request.ai_conviction,
            agreed_with_ai=agreed,
            snapshot_generated_at=request.snapshot_generated_at,
            recorded_at=recorded_at.astimezone(UTC),
            note=request.note,
            analysis_snapshot=request.analysis_snapshot,
            ai_review=request.ai_review,
        )

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
        accepted = sum(d.action == DecisionAction.ACCEPT for d in decisions)
        comparable = [d for d in decisions if d.agreed_with_ai is not None]
        agreed = sum(d.agreed_with_ai is True for d in comparable)
        return ManualDecisionStats(
            total=total,
            accepted=accepted,
            rejected=sum(d.action == DecisionAction.REJECT for d in decisions),
            deferred=sum(d.action == DecisionAction.DEFER for d in decisions),
            longs=sum(d.direction == DecisionDirection.LONG for d in decisions),
            shorts=sum(d.direction == DecisionDirection.SHORT for d in decisions),
            accept_rate=round(accepted / total, 4) if total else None,
            ai_comparable=len(comparable),
            agreed_with_ai=agreed,
            agreement_rate=round(agreed / len(comparable), 4) if comparable else None,
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
        snapshot_generated_at=_optional_datetime(row["snapshot_generated_at"]),
        recorded_at=_datetime(row["recorded_at"]),
        note=row["note"],
        analysis_snapshot=_load(row["analysis_snapshot_json"]),
        ai_review=_load(row["ai_review_json"]),
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
