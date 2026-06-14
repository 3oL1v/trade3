from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from .indicators import aligned_ema, atr
from .live_models import PriceZone, TradeTarget, TrendPullbackPlan
from .market_models import Candle

PULLBACK_LOOKBACK = 10
PIVOT_LOOKBACK = 60
MIN_STRUCTURAL_RR = 1.5
MAX_STOP_DISTANCE_ATR = 2.5


def build_trend_pullback_plan(
    direction: str,
    candles_5m: list[Candle],
    candles_15m: list[Candle],
    live_price: float,
    tick_size: float,
    score_state: str,
) -> TrendPullbackPlan | None:
    closed_5m = _closed(candles_5m)
    closed_15m = _closed(candles_15m)
    if len(closed_5m) < 55 or len(closed_15m) < 20 or direction not in {"long", "short"}:
        return None

    closes = [candle.close for candle in closed_5m]
    ema_20_values = aligned_ema(closes, 20)
    ema_50_values = aligned_ema(closes, 50)
    current_atr = atr(closed_5m, 14)
    current_ema_20 = _required(ema_20_values[-1])
    pullback_zone = _zone(
        current_ema_20 - current_atr * 0.20,
        current_ema_20 + current_atr * 0.20,
        tick_size,
    )

    touch_index = _find_touch(
        direction,
        closed_5m,
        ema_20_values,
        ema_50_values,
        current_atr,
    )
    if touch_index is None:
        return _waiting_pullback(
            direction,
            closed_5m,
            closed_15m,
            live_price,
            tick_size,
            current_atr,
            pullback_zone,
            score_state,
        )

    touch = closed_5m[touch_index]
    if direction == "long":
        trigger = _round_up(touch.high + tick_size, tick_size)
    else:
        trigger = _round_down(touch.low - tick_size, tick_size)

    confirmation_index = _find_confirmation(direction, closed_5m, touch_index, trigger)
    last_plan_index = confirmation_index if confirmation_index is not None else len(closed_5m) - 1
    pullback_candles = closed_5m[max(0, touch_index - 2) : last_plan_index + 1]
    entry_zone = _entry_zone(direction, trigger, current_atr, tick_size)
    invalidation = _invalidation(
        direction,
        pullback_candles,
        entry_zone,
        current_atr,
        tick_size,
    )
    conservative_entry = entry_zone.upper if direction == "long" else entry_zone.lower
    risk = abs(conservative_entry - invalidation)
    if risk <= 0:
        return None

    stop_distance_atr = risk / current_atr
    structural_target = _structural_target(
        direction,
        closed_15m,
        conservative_entry,
        tick_size,
    )
    structural_rr = (
        abs(structural_target - conservative_entry) / risk
        if structural_target is not None
        else None
    )
    notes = [
        "Entry requires a closed 5m confirmation beyond the trigger.",
        "Invalidation is beyond the pullback extreme with an ATR buffer.",
        "Levels are rounded to the Bybit instrument tick size.",
    ]
    status = _status(
        direction=direction,
        live_price=live_price,
        entry_zone=entry_zone,
        invalidation=invalidation,
        current_atr=current_atr,
        confirmation_exists=confirmation_index is not None,
        structural_rr=structural_rr,
        stop_distance_atr=stop_distance_atr,
        score_state=score_state,
        notes=notes,
    )
    targets = _targets(
        direction,
        conservative_entry,
        risk,
        structural_target,
        tick_size,
    )
    return TrendPullbackPlan(
        status=status,
        pullback_zone=pullback_zone,
        trigger_price=trigger,
        entry_zone=entry_zone,
        invalidation_price=invalidation,
        structural_target=structural_target,
        risk_per_unit=_round_nearest(risk, tick_size),
        structural_reward_risk=_rounded_positive(structural_rr),
        stop_distance_atr=round(stop_distance_atr, 2),
        touched_at=touch.start_time,
        confirmation_at=(
            closed_5m[confirmation_index].start_time if confirmation_index is not None else None
        ),
        targets=targets,
        notes=notes,
    )


def _waiting_pullback(
    direction: str,
    closed_5m: list[Candle],
    closed_15m: list[Candle],
    live_price: float,
    tick_size: float,
    current_atr: float,
    pullback_zone: PriceZone,
    score_state: str,
) -> TrendPullbackPlan:
    trigger = pullback_zone.upper if direction == "long" else pullback_zone.lower
    entry_zone = _entry_zone(direction, trigger, current_atr, tick_size)
    reference = closed_5m[-8:]
    invalidation = _invalidation(
        direction,
        reference,
        entry_zone,
        current_atr,
        tick_size,
    )
    conservative_entry = entry_zone.upper if direction == "long" else entry_zone.lower
    risk = abs(conservative_entry - invalidation)
    structural_target = _structural_target(
        direction,
        closed_15m,
        conservative_entry,
        tick_size,
    )
    structural_rr = (
        abs(structural_target - conservative_entry) / risk
        if structural_target is not None and risk
        else None
    )
    notes = ["No EMA20 pullback touch was found in the last 10 closed 5m candles."]
    stop_distance_atr = risk / current_atr
    status = "waiting_pullback"
    if structural_rr is None or structural_rr < MIN_STRUCTURAL_RR:
        status = "blocked"
        notes.append("Nearest 15m structure offers less than 1.5R.")
    elif stop_distance_atr > MAX_STOP_DISTANCE_ATR:
        status = "blocked"
        notes.append("Invalidation is farther than 2.5 ATR from the entry zone.")
    elif score_state != "candidate":
        status = "watch"
        notes.append("Setup score is below the candidate threshold.")
    return TrendPullbackPlan(
        status=status,
        pullback_zone=pullback_zone,
        trigger_price=trigger,
        entry_zone=entry_zone,
        invalidation_price=invalidation,
        structural_target=structural_target,
        risk_per_unit=_round_nearest(risk, tick_size),
        structural_reward_risk=_rounded_positive(structural_rr),
        stop_distance_atr=round(stop_distance_atr, 2),
        touched_at=None,
        confirmation_at=None,
        targets=_targets(
            direction,
            conservative_entry,
            risk,
            structural_target,
            tick_size,
        ),
        notes=notes,
    )


def _find_touch(
    direction: str,
    candles: list[Candle],
    ema_20_values: list[float | None],
    ema_50_values: list[float | None],
    current_atr: float,
) -> int | None:
    start = max(50, len(candles) - PULLBACK_LOOKBACK)
    for index in range(len(candles) - 1, start - 1, -1):
        ema_20 = _required(ema_20_values[index])
        ema_50 = _required(ema_50_values[index])
        candle = candles[index]
        zone_low = ema_20 - current_atr * 0.20
        zone_high = ema_20 + current_atr * 0.20
        overlaps = candle.low <= zone_high and candle.high >= zone_low
        trend_holds = candle.close > ema_50 if direction == "long" else candle.close < ema_50
        if overlaps and trend_holds:
            return index
    return None


def _find_confirmation(
    direction: str,
    candles: list[Candle],
    touch_index: int,
    trigger: float,
) -> int | None:
    for index in range(touch_index + 1, len(candles)):
        close = candles[index].close
        if (direction == "long" and close >= trigger) or (
            direction == "short" and close <= trigger
        ):
            return index
    return None


def _entry_zone(direction: str, trigger: float, current_atr: float, tick_size: float) -> PriceZone:
    tolerance = max(current_atr * 0.10, tick_size)
    if direction == "long":
        return _zone(trigger, trigger + tolerance, tick_size)
    return _zone(trigger - tolerance, trigger, tick_size)


def _invalidation(
    direction: str,
    candles: list[Candle],
    entry_zone: PriceZone,
    current_atr: float,
    tick_size: float,
) -> float:
    buffer = max(current_atr * 0.15, tick_size)
    minimum_risk = max(current_atr * 0.75, tick_size * 2)
    if direction == "long":
        structural = min(candle.low for candle in candles) - buffer
        minimum = entry_zone.upper - minimum_risk
        return _round_down(min(structural, minimum), tick_size)
    structural = max(candle.high for candle in candles) + buffer
    minimum = entry_zone.lower + minimum_risk
    return _round_up(max(structural, minimum), tick_size)


def _structural_target(
    direction: str,
    candles: list[Candle],
    entry: float,
    tick_size: float,
) -> float | None:
    recent = candles[-PIVOT_LOOKBACK:]
    pivots = _pivot_levels(recent, direction)
    if direction == "long":
        levels = [level for level in pivots if level > entry]
        fallback = max(candle.high for candle in recent)
        target = min(levels) if levels else (fallback if fallback > entry else None)
        return _round_down(target, tick_size) if target is not None else None
    levels = [level for level in pivots if level < entry]
    fallback = min(candle.low for candle in recent)
    target = max(levels) if levels else (fallback if fallback < entry else None)
    return _round_up(target, tick_size) if target is not None else None


def _pivot_levels(candles: list[Candle], direction: str) -> list[float]:
    values: list[float] = []
    for index in range(2, len(candles) - 2):
        window = candles[index - 2 : index + 3]
        if direction == "long":
            value = candles[index].high
            if value == max(candle.high for candle in window):
                values.append(value)
        else:
            value = candles[index].low
            if value == min(candle.low for candle in window):
                values.append(value)
    return values


def _status(
    *,
    direction: str,
    live_price: float,
    entry_zone: PriceZone,
    invalidation: float,
    current_atr: float,
    confirmation_exists: bool,
    structural_rr: float | None,
    stop_distance_atr: float,
    score_state: str,
    notes: list[str],
) -> str:
    if structural_rr is None or structural_rr < MIN_STRUCTURAL_RR:
        notes.append("Nearest 15m structure offers less than 1.5R.")
        return "blocked"
    if stop_distance_atr > MAX_STOP_DISTANCE_ATR:
        notes.append("Invalidation is farther than 2.5 ATR from the entry zone.")
        return "blocked"
    if score_state != "candidate":
        notes.append("Setup score is below the candidate threshold.")
        return "watch"
    if not confirmation_exists:
        return "waiting_confirmation"
    if (direction == "long" and live_price <= invalidation) or (
        direction == "short" and live_price >= invalidation
    ):
        notes.append("Live price crossed the invalidation level.")
        return "blocked"
    slippage = current_atr * 0.20
    if direction == "long":
        if live_price > entry_zone.upper + slippage:
            return "missed"
        if live_price >= entry_zone.lower:
            return "ready"
    else:
        if live_price < entry_zone.lower - slippage:
            return "missed"
        if live_price <= entry_zone.upper:
            return "ready"
    return "waiting_entry"


def _targets(
    direction: str,
    entry: float,
    risk: float,
    structural_target: float | None,
    tick_size: float,
) -> list[TradeTarget]:
    if risk <= 0:
        return []
    sign = 1 if direction == "long" else -1
    candidates = [
        ("TP1", entry + sign * risk),
        ("TP2", entry + sign * risk * 2),
    ]
    if structural_target is not None:
        candidates.append(("STRUCTURE", structural_target))
    targets: list[TradeTarget] = []
    seen: set[float] = set()
    for label, raw_price in candidates:
        if structural_target is not None:
            beyond_structure = (
                raw_price > structural_target
                if direction == "long"
                else raw_price < structural_target
            )
            if label != "STRUCTURE" and beyond_structure:
                continue
        target = (
            _round_down(raw_price, tick_size)
            if direction == "long"
            else _round_up(raw_price, tick_size)
        )
        rr = abs(target - entry) / risk
        rounded_rr = round(rr, 2)
        valid_side = target > entry if direction == "long" else target < entry
        if valid_side and rounded_rr > 0 and target not in seen:
            targets.append(TradeTarget(label=label, price=target, reward_risk=rounded_rr))
            seen.add(target)
    targets.sort(key=lambda item: item.reward_risk)
    return targets


def _closed(candles: list[Candle]) -> list[Candle]:
    return sorted(
        (candle for candle in candles if candle.is_closed),
        key=lambda candle: candle.start_time,
    )


def _zone(lower: float, upper: float, tick_size: float) -> PriceZone:
    return PriceZone(
        lower=_round_down(min(lower, upper), tick_size),
        upper=_round_up(max(lower, upper), tick_size),
    )


def _round_down(value: float, tick_size: float) -> float:
    return _round(value, tick_size, ROUND_FLOOR)


def _round_up(value: float, tick_size: float) -> float:
    return _round(value, tick_size, ROUND_CEILING)


def _round_nearest(value: float, tick_size: float) -> float:
    return _round(value, tick_size, ROUND_HALF_UP)


def _round(value: float, tick_size: float, rounding: str) -> float:
    tick = Decimal(str(tick_size))
    units = (Decimal(str(value)) / tick).to_integral_value(rounding=rounding)
    return float(units * tick)


def _required(value: float | None) -> float:
    if value is None:
        raise ValueError("EMA value is not available")
    return value


def _rounded_positive(value: float | None) -> float | None:
    if value is None:
        return None
    rounded = round(value, 2)
    return rounded if rounded > 0 else None
