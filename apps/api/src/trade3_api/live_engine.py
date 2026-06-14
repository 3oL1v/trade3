import asyncio
from datetime import UTC, datetime

from .bybit import BybitPublicClient
from .bybit_ws import BybitPublicStream
from .intraday import analyze_market, build_scan
from .journal import SignalJournal
from .live_models import EngineState, IntradayScan, LiveEngineStatus
from .live_store import LiveMarketStore
from .market_models import MarketUniverse
from .scanner import MarketScanner

INTRADAY_INTERVALS = ["5", "15", "60"]


class LiveMarketEngine:
    def __init__(
        self,
        client: BybitPublicClient,
        scanner: MarketScanner,
        store: LiveMarketStore,
        ws_url: str,
        universe_size: int,
        candle_limit: int,
        universe_refresh_seconds: int,
        max_backfill_concurrency: int,
        max_message_age_seconds: float,
        max_clock_skew_seconds: float,
        max_candidate_spread_bps: float,
        journal: SignalJournal | None = None,
        journal_scan_seconds: float = 5,
        enabled: bool = True,
    ) -> None:
        self._client = client
        self._scanner = scanner
        self._store = store
        self._stream = BybitPublicStream(ws_url, store.apply_message)
        self._universe_size = universe_size
        self._candle_limit = candle_limit
        self._universe_refresh_seconds = universe_refresh_seconds
        self._max_backfill_concurrency = max_backfill_concurrency
        self._max_message_age_seconds = max_message_age_seconds
        self._max_clock_skew_seconds = max_clock_skew_seconds
        self._max_candidate_spread_bps = max_candidate_spread_bps
        self._journal = journal
        self._journal_scan_seconds = journal_scan_seconds
        self._enabled = enabled
        self._state = EngineState.DISABLED if not enabled else EngineState.STOPPED
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._universe: MarketUniverse | None = None
        self._started_at: datetime | None = None
        self._last_refresh_at: datetime | None = None
        self._engine_error: str | None = None
        self._stream_error: str | None = None
        self._journal_error: str | None = None
        self._reconnect_count = 0

    async def start(self) -> None:
        if not self._enabled or self._task:
            return
        self._stop_event.clear()
        self._started_at = datetime.now(UTC)
        self._state = EngineState.STARTING
        self._task = asyncio.create_task(self._run(), name="trade3-live-market-engine")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        self._state = EngineState.STOPPED if self._enabled else EngineState.DISABLED

    async def status(self) -> LiveEngineStatus:
        last_message = await self._store.last_message_at()
        clock_skew = await self._store.clock_skew_seconds()
        ticker_count, candle_series_count = await self._store.counts()
        state = self._state
        if state == EngineState.RUNNING:
            if last_message is None:
                state = EngineState.STARTING
            elif (datetime.now(UTC) - last_message).total_seconds() > self._max_message_age_seconds:
                state = EngineState.DEGRADED
            elif clock_skew is not None and abs(clock_skew) > self._max_clock_skew_seconds:
                state = EngineState.DEGRADED
        return LiveEngineStatus(
            state=state,
            enabled=self._enabled,
            journal_enabled=self._journal is not None,
            symbols=[market.symbol for market in self._universe.markets] if self._universe else [],
            intervals=INTRADAY_INTERVALS,
            started_at=self._started_at,
            last_message_at=last_message,
            last_universe_refresh_at=self._last_refresh_at,
            reconnect_count=self._reconnect_count,
            last_error=self._current_error(),
            clock_skew_seconds=round(clock_skew, 3) if clock_skew is not None else None,
            clock_synchronized=(
                clock_skew is not None and abs(clock_skew) <= self._max_clock_skew_seconds
            ),
            ticker_count=ticker_count,
            candle_series_count=candle_series_count,
        )

    async def scan(self, limit: int) -> IntradayScan:
        status = await self.status()
        candidates = []
        if self._universe:
            for market in self._universe.markets:
                ticker = await self._store.ticker(market.symbol)
                if ticker is None:
                    continue
                candles = {
                    interval: await self._store.candles(market.symbol, interval)
                    for interval in INTRADAY_INTERVALS
                }
                candidate = analyze_market(
                    market.symbol,
                    ticker,
                    candles,
                    datetime.now(UTC),
                    max_spread_bps=self._max_candidate_spread_bps,
                    max_ticker_age_seconds=self._max_message_age_seconds,
                    tick_size=market.tick_size,
                )
                if candidate is not None:
                    candidates.append(candidate)
        return build_scan(self._universe, status.state, candidates, limit)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            stream_stop = asyncio.Event()
            try:
                self._state = EngineState.STARTING
                self._universe = await self._scanner.top_markets(self._universe_size)
                await self._backfill(self._universe)
                self._last_refresh_at = datetime.now(UTC)
                self._state = EngineState.RUNNING
                self._engine_error = None
                symbols = [market.symbol for market in self._universe.markets]
                stream_task = asyncio.create_task(
                    self._stream.run(
                        symbols,
                        INTRADAY_INTERVALS,
                        stream_stop,
                        self._on_reconnect,
                        self._on_stream_connected,
                    )
                )
                journal_task = (
                    asyncio.create_task(
                        self._journal_loop(stream_stop),
                        name="trade3-signal-journal",
                    )
                    if self._journal
                    else None
                )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._universe_refresh_seconds,
                    )
                except TimeoutError:
                    pass
                finally:
                    stream_stop.set()
                    stream_task.cancel()
                    if journal_task:
                        journal_task.cancel()
                    await asyncio.gather(
                        *(task for task in (stream_task, journal_task) if task),
                        return_exceptions=True,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state = EngineState.DEGRADED
                self._engine_error = str(exc)
                await _wait_or_stop(self._stop_event, 10)

    async def _backfill(self, universe: MarketUniverse) -> None:
        semaphore = asyncio.Semaphore(self._max_backfill_concurrency)

        async def seed(symbol: str, interval: str) -> None:
            async with semaphore:
                series = await self._client.get_candles(symbol, interval, self._candle_limit)
                await self._store.seed_candles(symbol, interval, series.candles)

        await asyncio.gather(
            *(
                seed(market.symbol, interval)
                for market in universe.markets
                for interval in INTRADAY_INTERVALS
            )
        )

    def _on_reconnect(self, error: str | None) -> None:
        self._reconnect_count += 1
        self._stream_error = error

    def _on_stream_connected(self) -> None:
        self._stream_error = None

    def _current_error(self) -> str | None:
        return self._engine_error or self._journal_error or self._stream_error

    async def _journal_loop(self, stop_event: asyncio.Event) -> None:
        if self._journal is None:
            return
        while not stop_event.is_set():
            try:
                scan = await self.scan(self._universe_size)
                await self._journal.record_candidates(scan.candidates, scan.generated_at)
                symbols = await self._journal.open_symbols()
                candles = {symbol: await self._store.candles(symbol, "5") for symbol in symbols}
                await self._journal.evaluate(candles, datetime.now(UTC))
                self._journal_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._journal_error = f"journal: {exc}"
            await _wait_or_stop(stop_event, self._journal_scan_seconds)


async def _wait_or_stop(stop_event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        pass
