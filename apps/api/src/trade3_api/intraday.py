from datetime import UTC, datetime, timedelta

from .indicators import timeframe_metrics
from .live_models import EngineState, IntradayCandidate, IntradayScan, LiveTicker
from .market_models import Candle, MarketUniverse
from .trade_plan import build_trend_pullback_plan

INTERVAL_MINUTES = {"5": 5, "15": 15, "60": 60}


def analyze_market(
    symbol: str,
    ticker: LiveTicker,
    candles_by_interval: dict[str, list[Candle]],
    now: datetime,
    max_spread_bps: float = 5,
    max_ticker_age_seconds: float = 15,
    tick_size: float = 0.01,
) -> IntradayCandidate | None:
    if (now - ticker.received_at).total_seconds() > max_ticker_age_seconds:
        return None
    midpoint = (ticker.bid_price + ticker.ask_price) / 2
    spread_bps = (ticker.ask_price - ticker.bid_price) / midpoint * 10_000
    if spread_bps > max_spread_bps:
        return None

    try:
        metrics_5m = timeframe_metrics(candles_by_interval["5"], "5")
        metrics_15m = timeframe_metrics(candles_by_interval["15"], "15")
        metrics_1h = timeframe_metrics(candles_by_interval["60"], "60")
    except (KeyError, ValueError):
        return None

    for metrics in (metrics_5m, metrics_15m, metrics_1h):
        close_time = metrics.last_closed_at + timedelta(minutes=INTERVAL_MINUTES[metrics.interval])
        if now - close_time > timedelta(minutes=INTERVAL_MINUTES[metrics.interval] * 2):
            return None

    direction = _trend_direction(metrics_1h)
    if direction == "neutral":
        return None

    score = 0.0
    reasons: list[str] = []
    long = direction == "long"

    score += 30
    reasons.append(f"1h EMA trend is {direction}")

    aligned_15m = _is_aligned(metrics_15m, long)
    if aligned_15m:
        score += 22
        reasons.append("15m structure aligns with 1h")

    aligned_5m = _is_aligned(metrics_5m, long)
    if aligned_5m:
        score += 12
        reasons.append("5m structure holds trend direction")

    pullback_distance = abs(metrics_5m.close - metrics_5m.ema_20) / metrics_5m.atr_14
    if pullback_distance > 2.5:
        return None
    if pullback_distance <= 0.75:
        score += 15
        reasons.append("price is near 5m EMA20 pullback zone")
    elif pullback_distance <= 1.5:
        score += 8
    else:
        score -= min((pullback_distance - 1.5) * 8, 15)
        reasons.append("price is extended from 5m EMA20")

    if metrics_5m.volume_ratio >= 1.2:
        score += 8
        reasons.append("5m closed-candle volume is above average")
    elif metrics_5m.volume_ratio >= 0.8:
        score += 4

    score += max(0, 8 - min(spread_bps, 8))

    if 0.15 <= metrics_5m.atr_percent <= 2.5:
        score += 5
    else:
        reasons.append("5m volatility is outside preferred range")

    score = round(max(0, min(score, 100)), 2)
    if pullback_distance > 1.5:
        score = min(score, 69.99)
    state = "candidate" if score >= 70 else "watch" if score >= 55 else "reject"
    trade_plan = build_trend_pullback_plan(
        direction=direction,
        candles_5m=candles_by_interval["5"],
        candles_15m=candles_by_interval["15"],
        live_price=ticker.last_price,
        tick_size=tick_size,
        score_state=state,
    )
    return IntradayCandidate(
        rank=1,
        symbol=symbol,
        direction=direction,
        score=score,
        state=state,
        last_price=ticker.last_price,
        spread_bps=round(spread_bps, 4),
        funding_rate_pct=round(ticker.funding_rate * 100, 6),
        turnover_24h_usdt=ticker.turnover_24h_usdt,
        open_interest_usdt=ticker.open_interest_usdt,
        pullback_distance_atr=round(pullback_distance, 4),
        timeframe_1h=metrics_1h,
        timeframe_15m=metrics_15m,
        timeframe_5m=metrics_5m,
        reasons=reasons,
        trade_plan=trade_plan,
    )


def build_scan(
    universe: MarketUniverse | None,
    engine_state: EngineState,
    candidates: list[IntradayCandidate],
    limit: int,
) -> IntradayScan:
    candidates.sort(key=lambda item: (item.score, item.turnover_24h_usdt), reverse=True)
    selected = [candidate for candidate in candidates if candidate.state != "reject"][:limit]
    for rank, candidate in enumerate(selected, start=1):
        candidate.rank = rank
    return IntradayScan(
        generated_at=datetime.now(UTC),
        engine_state=engine_state,
        universe_size=len(universe.markets) if universe else 0,
        analyzed_count=len(candidates),
        candidates=selected,
    )


def _trend_direction(metrics) -> str:
    separation = abs(metrics.ema_20 - metrics.ema_50) / metrics.atr_14
    if separation < 0.10:
        return "neutral"
    if metrics.ema_20 > metrics.ema_50 and metrics.ema_20_slope_pct > 0:
        return "long"
    if metrics.ema_20 < metrics.ema_50 and metrics.ema_20_slope_pct < 0:
        return "short"
    return "neutral"


def _is_aligned(metrics, long: bool) -> bool:
    if long:
        return metrics.close > metrics.ema_20 > metrics.ema_50
    return metrics.close < metrics.ema_20 < metrics.ema_50
