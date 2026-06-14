import tempfile
from bisect import bisect_right
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bybit import BybitPublicClient
from .intraday import analyze_market
from .journal import SignalJournal
from .journal_models import JournalSignal
from .live_models import LiveTicker
from .market_models import Candle
from .research_models import HistoricalReplayReport, ReplayBreakdown, ReplayTrade

INTERVAL_MINUTES = {"5": 5, "15": 15, "60": 60}
WINDOW_CANDLES = 300


class HistoricalReplay:
    def __init__(
        self,
        client: BybitPublicClient,
        *,
        spread_bps: float = 1,
        taker_fee_rate_pct: float = 0.055,
        slippage_bps: float = 2,
        warmup_days: int = 4,
    ) -> None:
        self._client = client
        self._spread_bps = spread_bps
        self._taker_fee_rate_pct = taker_fee_rate_pct
        self._slippage_bps = slippage_bps
        self._warmup_days = warmup_days

    async def run(
        self,
        symbols: list[str],
        tick_sizes: dict[str, float],
        start: datetime,
        end: datetime,
    ) -> HistoricalReplayReport:
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start >= end:
            raise ValueError("start must be before end")
        normalized_symbols = list(dict.fromkeys(symbol.upper() for symbol in symbols))
        missing = [symbol for symbol in normalized_symbols if symbol not in tick_sizes]
        if missing:
            raise ValueError(f"tick size is unavailable for: {', '.join(missing)}")

        signals: list[JournalSignal] = []
        with tempfile.TemporaryDirectory(prefix="trade3-replay-") as directory:
            for symbol in normalized_symbols:
                signals.extend(
                    await self._run_symbol(
                        symbol,
                        tick_sizes[symbol],
                        start,
                        end,
                        Path(directory) / f"{symbol}.sqlite3",
                    )
                )
        return _build_report(
            symbols=normalized_symbols,
            start=start,
            end=end,
            warmup_days=self._warmup_days,
            spread_bps=self._spread_bps,
            taker_fee_rate_pct=self._taker_fee_rate_pct,
            slippage_bps=self._slippage_bps,
            signals=signals,
        )

    async def _run_symbol(
        self,
        symbol: str,
        tick_size: float,
        start: datetime,
        end: datetime,
        database_path: Path,
    ) -> list[JournalSignal]:
        history_start = start - timedelta(days=self._warmup_days)
        candles = {
            interval: await self._client.get_historical_candles(
                symbol,
                interval,
                history_start,
                end,
            )
            for interval in INTERVAL_MINUTES
        }
        close_times = {
            interval: [
                candle.start_time + timedelta(minutes=INTERVAL_MINUTES[interval])
                for candle in series
            ]
            for interval, series in candles.items()
        }
        journal = SignalJournal(
            str(database_path),
            taker_fee_rate_pct=self._taker_fee_rate_pct,
            slippage_bps=self._slippage_bps,
        )
        await journal.initialize()

        for index, current in enumerate(candles["5"]):
            evaluation_at = current.start_time + timedelta(minutes=5)
            if evaluation_at < start or evaluation_at >= end:
                continue
            await journal.evaluate({symbol: [current]}, evaluation_at)
            if symbol in await journal.unresolved_execution_symbols():
                continue

            windows = {
                interval: _closed_window(
                    candles[interval],
                    close_times[interval],
                    evaluation_at,
                )
                for interval in INTERVAL_MINUTES
            }
            if any(len(windows[interval]) < 60 for interval in INTERVAL_MINUTES):
                continue
            candidate = analyze_market(
                symbol=symbol,
                ticker=_historical_ticker(
                    symbol,
                    current,
                    evaluation_at,
                    candles["5"][max(0, index - 287) : index + 1],
                    self._spread_bps,
                ),
                candles_by_interval=windows,
                now=evaluation_at,
                max_spread_bps=max(self._spread_bps + 0.01, 0.01),
                max_ticker_age_seconds=1,
                tick_size=tick_size,
            )
            if candidate is None or candidate.trade_plan is None:
                continue
            confirmation_at = candidate.trade_plan.confirmation_at
            if confirmation_at is None or confirmation_at + timedelta(minutes=5) != evaluation_at:
                continue
            await journal.record_candidates([candidate], evaluation_at)

        return await journal.list_signals(limit=100_000)


def _closed_window(
    candles: list[Candle],
    close_times: list[datetime],
    evaluation_at: datetime,
) -> list[Candle]:
    end_index = bisect_right(close_times, evaluation_at)
    return candles[max(0, end_index - WINDOW_CANDLES) : end_index]


def _historical_ticker(
    symbol: str,
    candle: Candle,
    evaluation_at: datetime,
    turnover_window: list[Candle],
    spread_bps: float,
) -> LiveTicker:
    half_spread = spread_bps / 20_000
    return LiveTicker(
        symbol=symbol,
        last_price=candle.close,
        mark_price=candle.close,
        bid_price=candle.close * (1 - half_spread),
        ask_price=candle.close * (1 + half_spread),
        turnover_24h_usdt=sum(item.turnover_usdt for item in turnover_window),
        open_interest_usdt=0,
        funding_rate=0,
        source_time=evaluation_at,
        received_at=evaluation_at,
    )


def _build_report(
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
    warmup_days: int,
    spread_bps: float,
    taker_fee_rate_pct: float,
    slippage_bps: float,
    signals: list[JournalSignal],
) -> HistoricalReplayReport:
    trades = [
        ReplayTrade(
            symbol=signal.symbol,
            direction=signal.direction,
            score=signal.score,
            signal_at=signal.signal_at,
            entered_at=signal.entered_at,
            closed_at=signal.closed_at,
            outcome=signal.outcome,
            gross_result_r=signal.result_r,
            net_result_r=signal.net_result_r,
            fee_cost_r=signal.fee_cost_r,
            slippage_cost_r=signal.slippage_cost_r,
        )
        for signal in signals
        if signal.entered_at is not None
        and signal.result_r is not None
        and signal.net_result_r is not None
        and signal.fee_cost_r is not None
        and signal.slippage_cost_r is not None
    ]
    trades.sort(key=lambda trade: (trade.signal_at, trade.symbol))
    gross_results = [trade.gross_result_r for trade in trades]
    net_results = [trade.net_result_r for trade in trades]
    fee_costs = [trade.fee_cost_r for trade in trades]
    slippage_costs = [trade.slippage_cost_r for trade in trades]
    return HistoricalReplayReport(
        generated_at=datetime.now(UTC),
        symbols=symbols,
        start=start,
        end=end,
        warmup_days=warmup_days,
        spread_bps=spread_bps,
        taker_fee_rate_pct=taker_fee_rate_pct,
        slippage_bps=slippage_bps,
        total_recorded_signals=len(signals),
        resolved_trades=len(trades),
        censored_signals=sum(
            signal.lifecycle_state in {"pending_entry", "active"} and signal.net_result_r is None
            for signal in signals
        ),
        ambiguous_signals=sum(signal.outcome == "ambiguous" for signal in signals),
        gross_expectancy_r=_average(gross_results),
        net_expectancy_r=_average(net_results),
        average_fee_cost_r=_average(fee_costs),
        average_slippage_cost_r=_average(slippage_costs),
        average_total_cost_r=_average(
            [trade.fee_cost_r + trade.slippage_cost_r for trade in trades]
        ),
        overall=_breakdown("all", trades),
        score_buckets=[
            _breakdown("70-79.99", [trade for trade in trades if 70 <= trade.score < 80]),
            _breakdown("80-89.99", [trade for trade in trades if 80 <= trade.score < 90]),
            _breakdown("90-100", [trade for trade in trades if trade.score >= 90]),
        ],
        directions=[
            _breakdown("long", [trade for trade in trades if trade.direction == "long"]),
            _breakdown("short", [trade for trade in trades if trade.direction == "short"]),
        ],
        trades=trades,
        limitations=[
            "Price-only replay: historical bid/ask, open interest, and funding are unavailable.",
            "A fixed spread is used in scoring and execution assumptions.",
            "The supplied symbol list is fixed and therefore subject to survivorship bias.",
            "OHLC candles cannot resolve intrabar ordering; ambiguous signals are excluded.",
            "Funding, latency, liquidation, and real order-book impact are not modeled.",
        ],
    )


def _breakdown(label: str, trades: list[ReplayTrade]) -> ReplayBreakdown:
    results = [trade.net_result_r for trade in trades]
    wins = [result for result in results if result > 0]
    losses = [result for result in results if result < 0]
    return ReplayBreakdown(
        label=label,
        trades=len(results),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(results), 4) if results else None,
        expectancy_r=round(sum(results) / len(results), 4) if results else None,
        profit_factor=round(sum(wins) / abs(sum(losses)), 4) if wins and losses else None,
        cumulative_net_r=round(sum(results), 4) if results else None,
        max_drawdown_r=_max_drawdown(results),
    )


def _max_drawdown(results: list[float]) -> float | None:
    if not results:
        return None
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for result in results:
        equity += result
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round(maximum, 4)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None
