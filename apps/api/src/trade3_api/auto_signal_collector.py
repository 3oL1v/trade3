import asyncio
import logging
from datetime import UTC, datetime

from .auto_signal_journal import AutoSignalJournal
from .auto_signal_models import AutoSignalRequest
from .bybit import BybitApiError, BybitPublicClient
from .live_store import LiveMarketStore
from .market_analysis import analyze_market_snapshot
from .scanner import MarketDataStaleError, MarketScanner

logger = logging.getLogger(__name__)

_INTERVALS = ("5", "15", "60", "240")


class AutoSignalCollector:
    """Periodically snapshots the system's directional call and scores it later.

    The collector takes the human out of the measurement loop: every scan it
    records ``preferred_direction`` for each symbol in the universe, and once a
    signal is older than the horizon it resolves the forward return against a
    buy-and-hold benchmark. This isolates whether the rule set has any edge from
    whether a person trades it well.
    """

    def __init__(
        self,
        *,
        client: BybitPublicClient,
        scanner: MarketScanner,
        store: LiveMarketStore,
        journal: AutoSignalJournal,
        benchmark_symbol: str,
        universe_size: int,
        scan_seconds: float,
        horizon_hours: float,
        startup_delay_seconds: float = 60.0,
        enabled: bool = True,
    ) -> None:
        self._client = client
        self._scanner = scanner
        self._store = store
        self._journal = journal
        self._benchmark_symbol = benchmark_symbol
        self._universe_size = universe_size
        self._scan_seconds = scan_seconds
        self._horizon_hours = horizon_hours
        self._startup_delay_seconds = startup_delay_seconds
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="auto-signal-collector")

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
                logger.exception("auto-signal collector cycle failed")
            await asyncio.sleep(self._scan_seconds)

    async def _collect(self) -> None:
        try:
            universe = await self._scanner.top_markets(self._universe_size)
        except (MarketDataStaleError, BybitApiError):
            logger.warning("auto-signal collector skipped a cycle: universe unavailable")
            return
        benchmark_price = await self._price(self._benchmark_symbol)
        now = datetime.now(UTC)
        for market in universe.markets[: self._universe_size]:
            snapshot = await self._snapshot(market.symbol)
            if snapshot is None:
                continue
            await self._journal.record(
                AutoSignalRequest(
                    symbol=market.symbol,
                    direction=snapshot.preferred_direction,
                    decision_price=snapshot.last_price,
                    generated_at=snapshot.generated_at,
                    benchmark_symbol=self._benchmark_symbol,
                    benchmark_price=benchmark_price,
                ),
                now,
            )

    async def _resolve_due(self) -> None:
        due = await self._journal.due_unresolved(self._horizon_hours)
        if not due:
            return
        benchmark_price = await self._price(self._benchmark_symbol)
        now = datetime.now(UTC)
        for signal in due:
            price = await self._price(signal.symbol)
            if price is None:
                continue
            await self._journal.resolve(signal.id, price, benchmark_price, now)

    async def _snapshot(self, symbol: str):
        async def candles(interval: str):
            cached = await self._store.candles(symbol, interval)
            if len(cached) >= 80:
                return cached
            series = await self._client.get_candles(symbol, interval, 300)
            return series.candles

        try:
            series = await asyncio.gather(*(candles(interval) for interval in _INTERVALS))
            ticker = await self._store.ticker(symbol)
            return analyze_market_snapshot(
                symbol=symbol,
                candles_by_interval=dict(zip(_INTERVALS, series, strict=True)),
                last_price=ticker.last_price if ticker else None,
            )
        except (ValueError, BybitApiError):
            return None

    async def _price(self, symbol: str) -> float | None:
        ticker = await self._store.ticker(symbol)
        if ticker and ticker.last_price:
            return ticker.last_price
        try:
            series = await self._client.get_candles(symbol, "5", 1)
        except BybitApiError:
            return None
        return series.candles[-1].close if series.candles else None
