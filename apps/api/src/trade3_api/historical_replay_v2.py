from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .bybit import BybitPublicClient
from .execution import model_execution
from .historical_replay import (
    INTERVAL_MINUTES,
    _average,
    _breakdown,
    _closed_window,
)
from .market_models import Candle
from .research_models import HistoricalReplayReport, ReplayTrade
from .strategy_v2 import (
    DEFAULT_PARAMETERS,
    TARGET_R,
    StrategyV2Parameters,
    V2Signal,
    find_v2_signal,
)

MAX_HOLD = timedelta(hours=12)


@dataclass
class _Position:
    signal: V2Signal
    entry_price: float
    stop_price: float
    target_price: float
    entered_at: datetime


class V2HistoricalReplay:
    def __init__(
        self,
        client: BybitPublicClient,
        *,
        spread_bps: float = 1,
        taker_fee_rate_pct: float = 0.055,
        slippage_bps: float = 2,
        warmup_days: int = 7,
        parameters: StrategyV2Parameters = DEFAULT_PARAMETERS,
    ) -> None:
        self._client = client
        self._spread_bps = spread_bps
        self._taker_fee_rate_pct = taker_fee_rate_pct
        self._slippage_bps = slippage_bps
        self._warmup_days = warmup_days
        self._parameters = parameters

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
        normalized = list(dict.fromkeys(symbol.upper() for symbol in symbols))
        missing = [symbol for symbol in normalized if symbol not in tick_sizes]
        if missing:
            raise ValueError(f"tick size is unavailable for: {', '.join(missing)}")

        candles_by_symbol = {}
        for symbol in normalized:
            history_start = start - timedelta(days=self._warmup_days)
            candles_by_symbol[symbol] = {
                interval: await self._client.get_historical_candles(
                    symbol,
                    interval,
                    history_start,
                    end,
                )
                for interval in INTERVAL_MINUTES
            }
        return self.run_cached(normalized, tick_sizes, start, end, candles_by_symbol)

    def run_cached(
        self,
        symbols: list[str],
        tick_sizes: dict[str, float],
        start: datetime,
        end: datetime,
        candles_by_symbol: dict[str, dict[str, list[Candle]]],
    ) -> HistoricalReplayReport:
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start >= end:
            raise ValueError("start must be before end")
        normalized = list(dict.fromkeys(symbol.upper() for symbol in symbols))
        missing = [symbol for symbol in normalized if symbol not in tick_sizes]
        if missing:
            raise ValueError(f"tick size is unavailable for: {', '.join(missing)}")
        missing_candles = [symbol for symbol in normalized if symbol not in candles_by_symbol]
        if missing_candles:
            raise ValueError(f"candles are unavailable for: {', '.join(missing_candles)}")

        trades: list[ReplayTrade] = []
        total_signals = 0
        ambiguous = 0
        censored = 0
        skipped = 0
        for symbol in normalized:
            result = self._run_symbol(
                symbol,
                tick_sizes[symbol],
                start,
                end,
                candles_by_symbol[symbol],
            )
            trades.extend(result.trades)
            total_signals += result.total_signals
            ambiguous += result.ambiguous
            censored += result.censored
            skipped += result.skipped
        trades.sort(key=lambda trade: (trade.signal_at, trade.symbol))
        return _report(
            symbols=normalized,
            start=start,
            end=end,
            warmup_days=self._warmup_days,
            spread_bps=self._spread_bps,
            taker_fee_rate_pct=self._taker_fee_rate_pct,
            slippage_bps=self._slippage_bps,
            total_signals=total_signals,
            ambiguous=ambiguous,
            censored=censored,
            skipped=skipped,
            trades=trades,
        )

    def _run_symbol(
        self,
        symbol: str,
        tick_size: float,
        start: datetime,
        end: datetime,
        candles: dict[str, list[Candle]],
    ) -> "_SymbolResult":
        close_times = {
            interval: [
                candle.start_time + timedelta(minutes=INTERVAL_MINUTES[interval])
                for candle in series
            ]
            for interval, series in candles.items()
        }
        pending: V2Signal | None = None
        position: _Position | None = None
        trades: list[ReplayTrade] = []
        total_signals = 0
        ambiguous = 0
        skipped = 0

        for current in candles["5"]:
            if current.start_time < start or current.start_time >= end:
                continue
            if pending is not None and pending.signal_at == current.start_time:
                position = _open_position(
                    pending,
                    current.open,
                    self._parameters.target_r,
                )
                pending = None
                if (
                    position is None
                    or _target_cost(position, self) > self._parameters.max_modeled_cost_r
                ):
                    position = None
                    skipped += 1
            if position is not None:
                outcome = _evaluate_position(
                    position,
                    current,
                    self._taker_fee_rate_pct,
                    self._slippage_bps,
                    timedelta(hours=self._parameters.max_hold_hours),
                )
                if outcome == "ambiguous":
                    ambiguous += 1
                    position = None
                elif isinstance(outcome, ReplayTrade):
                    trades.append(outcome)
                    position = None

            evaluation_at = current.start_time + timedelta(minutes=5)
            if evaluation_at < start or evaluation_at >= end:
                continue
            if pending is not None or position is not None or evaluation_at.minute % 15:
                continue
            signal = find_v2_signal(
                symbol=symbol,
                candles_15m=_closed_window(
                    candles["15"],
                    close_times["15"],
                    evaluation_at,
                ),
                candles_1h=_closed_window(
                    candles["60"],
                    close_times["60"],
                    evaluation_at,
                ),
                evaluation_at=evaluation_at,
                tick_size=tick_size,
                taker_fee_rate_pct=self._taker_fee_rate_pct,
                slippage_bps=self._slippage_bps,
                parameters=self._parameters,
            )
            if signal is not None:
                pending = signal
                total_signals += 1

        censored = int(pending is not None) + int(position is not None)
        return _SymbolResult(
            trades=trades,
            total_signals=total_signals,
            ambiguous=ambiguous,
            censored=censored,
            skipped=skipped,
        )


@dataclass
class _SymbolResult:
    trades: list[ReplayTrade]
    total_signals: int
    ambiguous: int
    censored: int
    skipped: int


def _open_position(
    signal: V2Signal,
    entry_price: float,
    target_r: float = TARGET_R,
) -> _Position | None:
    if signal.direction == "long" and entry_price <= signal.stop_price:
        return None
    if signal.direction == "short" and entry_price >= signal.stop_price:
        return None
    risk = abs(entry_price - signal.stop_price)
    target = entry_price + (risk * target_r if signal.direction == "long" else -risk * target_r)
    return _Position(
        signal=signal,
        entry_price=entry_price,
        stop_price=signal.stop_price,
        target_price=target,
        entered_at=signal.signal_at,
    )


def _target_cost(position: _Position, replay: V2HistoricalReplay) -> float:
    result = model_execution(
        direction=position.signal.direction,
        entry_price=position.entry_price,
        stop_price=position.stop_price,
        exit_reference_price=position.target_price,
        taker_fee_rate_pct=replay._taker_fee_rate_pct,
        slippage_bps=replay._slippage_bps,
    )
    return result.fee_cost_r + result.slippage_cost_r


def _evaluate_position(
    position: _Position,
    candle: Candle,
    taker_fee_rate_pct: float,
    slippage_bps: float,
    max_hold: timedelta = MAX_HOLD,
) -> ReplayTrade | str | None:
    long = position.signal.direction == "long"
    stop_touched = candle.low <= position.stop_price if long else candle.high >= position.stop_price
    target_touched = (
        candle.high >= position.target_price if long else candle.low <= position.target_price
    )
    if stop_touched and target_touched:
        return "ambiguous"
    exit_price: float | None = None
    outcome: str | None = None
    if target_touched:
        exit_price, outcome = position.target_price, "target_complete"
    elif stop_touched:
        exit_price, outcome = position.stop_price, "stop_before_target"
    elif candle.start_time + timedelta(minutes=5) - position.entered_at >= max_hold:
        exit_price, outcome = candle.close, "expired_active"
    if exit_price is None:
        return None
    execution = model_execution(
        direction=position.signal.direction,
        entry_price=position.entry_price,
        stop_price=position.stop_price,
        exit_reference_price=exit_price,
        taker_fee_rate_pct=taker_fee_rate_pct,
        slippage_bps=slippage_bps,
    )
    return ReplayTrade(
        symbol=position.signal.symbol,
        direction=position.signal.direction,
        score=position.signal.score,
        signal_at=position.signal.signal_at,
        entered_at=position.entered_at,
        closed_at=candle.start_time,
        outcome=outcome,
        gross_result_r=execution.gross_result_r,
        net_result_r=execution.net_result_r,
        fee_cost_r=execution.fee_cost_r,
        slippage_cost_r=execution.slippage_cost_r,
    )


def _report(
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
    warmup_days: int,
    spread_bps: float,
    taker_fee_rate_pct: float,
    slippage_bps: float,
    total_signals: int,
    ambiguous: int,
    censored: int,
    skipped: int,
    trades: list[ReplayTrade],
) -> HistoricalReplayReport:
    gross = [trade.gross_result_r for trade in trades]
    net = [trade.net_result_r for trade in trades]
    fees = [trade.fee_cost_r for trade in trades]
    slippage = [trade.slippage_cost_r for trade in trades]
    return HistoricalReplayReport(
        generated_at=datetime.now(UTC),
        strategy="trend_continuation_v2",
        execution_policy="next_5m_open_2r_or_stop_v2",
        symbols=symbols,
        start=start,
        end=end,
        warmup_days=warmup_days,
        spread_bps=spread_bps,
        taker_fee_rate_pct=taker_fee_rate_pct,
        slippage_bps=slippage_bps,
        total_recorded_signals=total_signals,
        resolved_trades=len(trades),
        censored_signals=censored,
        ambiguous_signals=ambiguous,
        skipped_signals=skipped,
        gross_expectancy_r=_average(gross),
        net_expectancy_r=_average(net),
        average_fee_cost_r=_average(fees),
        average_slippage_cost_r=_average(slippage),
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
            "V2 was specified after V1 failed on a later, non-overlapping period.",
            "Price-only replay uses a fixed spread and fixed symbol list.",
            "Historical open interest, funding, latency, and market impact are not modeled.",
            "Intrabar stop/target conflicts are excluded as ambiguous.",
        ],
    )
