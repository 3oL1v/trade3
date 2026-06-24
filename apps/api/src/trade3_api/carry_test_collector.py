import asyncio
import logging
from datetime import UTC, datetime

from .bybit import BybitApiError, BybitPublicClient
from .carry_test_journal import CarryTestJournal, realized_carry_pct
from .carry_test_models import CarryPositionRequest
from .funding_carry import build_carry_board

logger = logging.getLogger(__name__)


class CarryTestCollector:
    """Opens paper market-neutral carry positions and scores realized net carry.

    Each cycle it snapshots the top funding-carry opportunities and records a
    position. Once a position is older than the horizon it resolves by summing
    the funding that actually printed over the holding window, minus the
    round-trip fees — so it measures realized carry, not the entry-time estimate.
    """

    def __init__(
        self,
        *,
        client: BybitPublicClient,
        journal: CarryTestJournal,
        taker_fee_rate_pct: float,
        min_turnover_24h_usdt: float,
        min_open_interest_usdt: float,
        max_spread_bps: float,
        allowed_base_coins: set[str] | None,
        top_n: int,
        scan_seconds: float,
        horizon_hours: float,
        startup_delay_seconds: float = 90.0,
        enabled: bool = True,
    ) -> None:
        self._client = client
        self._journal = journal
        self._taker_fee_rate_pct = taker_fee_rate_pct
        self._min_turnover_24h_usdt = min_turnover_24h_usdt
        self._min_open_interest_usdt = min_open_interest_usdt
        self._max_spread_bps = max_spread_bps
        self._allowed_base_coins = allowed_base_coins
        self._top_n = top_n
        self._scan_seconds = scan_seconds
        self._horizon_hours = horizon_hours
        self._startup_delay_seconds = startup_delay_seconds
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="carry-test-collector")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(self._startup_delay_seconds)
        while True:
            try:
                await self._resolve_due()
                await self._collect()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - background loop must not die
                logger.exception("carry-test collector cycle failed")
            await asyncio.sleep(self._scan_seconds)

    async def _collect(self) -> None:
        try:
            board = await build_carry_board(
                self._client,
                limit=self._top_n,
                taker_fee_rate_pct=self._taker_fee_rate_pct,
                min_turnover_24h_usdt=self._min_turnover_24h_usdt,
                min_open_interest_usdt=self._min_open_interest_usdt,
                max_spread_bps=self._max_spread_bps,
                allowed_base_coins=self._allowed_base_coins,
                with_history=False,
            )
        except BybitApiError:
            logger.warning("carry-test collector skipped a cycle: carry board unavailable")
            return
        now = datetime.now(UTC)
        for opportunity in board.opportunities:
            await self._journal.record(
                CarryPositionRequest(
                    symbol=opportunity.symbol,
                    side=opportunity.side,
                    entry_funding_rate_pct=opportunity.funding_rate_pct,
                    entry_apr_pct=opportunity.annualized_apr_pct,
                    funding_interval_hours=opportunity.funding_interval_hours,
                    round_trip_fee_pct=board.round_trip_fee_pct,
                ),
                now,
            )

    async def _resolve_due(self) -> None:
        due = await self._journal.due_unresolved(self._horizon_hours)
        if not due:
            return
        now = datetime.now(UTC)
        for position in due:
            try:
                history = await self._client.get_funding_history(position.symbol, limit=200)
            except (BybitApiError, ValueError):
                continue
            window = [
                rate
                for timestamp, rate in history
                if position.opened_at < timestamp <= now
            ]
            realized = realized_carry_pct(position.side, sum(window))
            await self._journal.resolve(position.id, realized, len(window), now)
