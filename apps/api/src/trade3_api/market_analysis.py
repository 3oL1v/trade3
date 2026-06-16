from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean

from .analysis_models import (
    AnalysisTrendLine,
    AnalysisZone,
    FlagPattern,
    MarketAnalysisSnapshot,
    MarketBias,
    ScenarioTarget,
    StructureEvent,
    SwingPoint,
    TimeframeStructure,
    TradeScenario,
    ZoneKind,
)
from .indicators import atr
from .live_models import PriceZone
from .market_models import Candle

TIMEFRAME_ORDER = ("240", "60", "15", "5")
TIMEFRAME_WEIGHT = {"240": 4, "60": 3, "15": 2, "5": 1}


def analyze_market_snapshot(
    *,
    symbol: str,
    candles_by_interval: dict[str, list[Candle]],
    last_price: float | None = None,
    generated_at: datetime | None = None,
) -> MarketAnalysisSnapshot:
    structures: list[TimeframeStructure] = []
    zones: list[AnalysisZone] = []
    trend_lines: list[AnalysisTrendLine] = []
    flags: list[FlagPattern] = []

    for timeframe in TIMEFRAME_ORDER:
        candles = _closed(candles_by_interval.get(timeframe, []))
        if len(candles) < 30:
            continue
        current_atr = atr(candles, 14)
        highs, lows = _swing_points(candles, timeframe)
        structure = _structure(candles, timeframe, current_atr, highs, lows)
        structures.append(structure)
        zones.extend(_level_zones(candles, timeframe, current_atr, highs, lows))
        zones.extend(_fair_value_gaps(candles, timeframe, current_atr))
        zones.extend(_order_blocks(candles, timeframe, current_atr))
        trend_lines.extend(_trend_lines(candles, timeframe, current_atr, highs, lows))
        flags.extend(_flag_patterns(candles, timeframe, current_atr))

    if not structures:
        raise ValueError("at least one timeframe with 30 closed candles is required")
    current_price = last_price or structures[-1].last_close
    zones = _deduplicate_zones(zones, current_price)
    scenarios = _build_scenarios(current_price, structures, zones)
    preferred = _preferred_direction(scenarios)
    decision = _decision(preferred, scenarios)
    return MarketAnalysisSnapshot(
        symbol=symbol.upper(),
        generated_at=generated_at or datetime.now(UTC),
        last_price=current_price,
        preferred_direction=preferred,
        decision=decision,
        structures=structures,
        zones=zones,
        trend_lines=trend_lines,
        flags=flags,
        scenarios=scenarios,
    )


def _closed(candles: list[Candle]) -> list[Candle]:
    return sorted(
        (candle for candle in candles if candle.is_closed),
        key=lambda candle: candle.start_time,
    )


def _swing_points(
    candles: list[Candle],
    timeframe: str,
    wing: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    for index in range(wing, len(candles) - wing):
        candle = candles[index]
        left = candles[index - wing : index]
        right = candles[index + 1 : index + wing + 1]
        if candle.high > max(item.high for item in left) and candle.high >= max(
            item.high for item in right
        ):
            highs.append(
                SwingPoint(
                    timeframe=timeframe,
                    kind="high",
                    time=candle.start_time,
                    price=candle.high,
                    strength=wing,
                )
            )
        if candle.low < min(item.low for item in left) and candle.low <= min(
            item.low for item in right
        ):
            lows.append(
                SwingPoint(
                    timeframe=timeframe,
                    kind="low",
                    time=candle.start_time,
                    price=candle.low,
                    strength=wing,
                )
            )
    return highs[-12:], lows[-12:]


def _structure(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
    highs: list[SwingPoint],
    lows: list[SwingPoint],
) -> TimeframeStructure:
    bias = MarketBias.RANGE
    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs[-1].price > highs[-2].price
        higher_low = lows[-1].price > lows[-2].price
        lower_high = highs[-1].price < highs[-2].price
        lower_low = lows[-1].price < lows[-2].price
        if higher_high and higher_low:
            bias = MarketBias.BULLISH
        elif lower_high and lower_low:
            bias = MarketBias.BEARISH
    elif len(highs) < 1 or len(lows) < 1:
        bias = MarketBias.INSUFFICIENT

    events: list[StructureEvent] = []
    close = candles[-1].close
    if len(highs) >= 2 and close > highs[-2].price:
        event_kind = "choch_up" if bias == MarketBias.BEARISH else "bos_up"
        events.append(
            StructureEvent(
                timeframe=timeframe,
                kind=event_kind,
                time=candles[-1].start_time,
                price=highs[-2].price,
                description="Latest close is above the prior confirmed swing high.",
            )
        )
    if len(lows) >= 2 and close < lows[-2].price:
        event_kind = "choch_down" if bias == MarketBias.BULLISH else "bos_down"
        events.append(
            StructureEvent(
                timeframe=timeframe,
                kind=event_kind,
                time=candles[-1].start_time,
                price=lows[-2].price,
                description="Latest close is below the prior confirmed swing low.",
            )
        )
    summary = {
        MarketBias.BULLISH: "Higher swing highs and higher swing lows.",
        MarketBias.BEARISH: "Lower swing highs and lower swing lows.",
        MarketBias.RANGE: "Swing sequence is mixed; directional structure is not clean.",
        MarketBias.INSUFFICIENT: "Not enough confirmed pivots for structure classification.",
    }[bias]
    return TimeframeStructure(
        timeframe=timeframe,
        bias=bias,
        last_close=close,
        atr=current_atr,
        swing_highs=highs[-5:],
        swing_lows=lows[-5:],
        events=events,
        summary=summary,
    )


def _level_zones(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
    highs: list[SwingPoint],
    lows: list[SwingPoint],
) -> list[AnalysisZone]:
    end_time = candles[-1].start_time
    zones = [
        *_cluster_levels(
            lows,
            timeframe,
            ZoneKind.SUPPORT,
            current_atr,
            end_time,
        ),
        *_cluster_levels(
            highs,
            timeframe,
            ZoneKind.RESISTANCE,
            current_atr,
            end_time,
        ),
    ]
    zones.extend(
        _liquidity_zones(
            highs,
            timeframe,
            ZoneKind.LIQUIDITY_HIGH,
            current_atr,
            end_time,
        )
    )
    zones.extend(
        _liquidity_zones(
            lows,
            timeframe,
            ZoneKind.LIQUIDITY_LOW,
            current_atr,
            end_time,
        )
    )
    return zones


def _cluster_levels(
    points: list[SwingPoint],
    timeframe: str,
    kind: ZoneKind,
    current_atr: float,
    end_time: datetime,
) -> list[AnalysisZone]:
    clusters = _clusters(points, current_atr * 0.35)
    result = []
    for index, cluster in enumerate(clusters):
        center = fmean(point.price for point in cluster)
        half_width = current_atr * 0.14
        result.append(
            AnalysisZone(
                id=f"{timeframe}-{kind}-{index}-{int(cluster[-1].time.timestamp())}",
                timeframe=timeframe,
                kind=kind,
                lower=max(center - half_width, 1e-12),
                upper=center + half_width,
                start_time=cluster[0].time,
                end_time=end_time,
                status="active",
                strength="high" if len(cluster) >= 3 else "medium",
                touches=len(cluster),
                rationale=f"{len(cluster)} confirmed swing reaction(s) cluster near this price.",
            )
        )
    return result


def _liquidity_zones(
    points: list[SwingPoint],
    timeframe: str,
    kind: ZoneKind,
    current_atr: float,
    end_time: datetime,
) -> list[AnalysisZone]:
    clusters = [cluster for cluster in _clusters(points, current_atr * 0.16) if len(cluster) >= 2]
    result = []
    for index, cluster in enumerate(clusters):
        prices = [point.price for point in cluster]
        result.append(
            AnalysisZone(
                id=f"{timeframe}-{kind}-{index}-{int(cluster[-1].time.timestamp())}",
                timeframe=timeframe,
                kind=kind,
                lower=max(min(prices) - current_atr * 0.04, 1e-12),
                upper=max(prices) + current_atr * 0.04,
                start_time=cluster[0].time,
                end_time=end_time,
                status="active",
                strength="high" if len(cluster) >= 3 else "medium",
                touches=len(cluster),
                rationale="Repeated similar swing prices form a visible liquidity pool.",
            )
        )
    return result


def _clusters(points: list[SwingPoint], tolerance: float) -> list[list[SwingPoint]]:
    clusters: list[list[SwingPoint]] = []
    for point in sorted(points, key=lambda item: item.time):
        matching = next(
            (
                cluster
                for cluster in clusters
                if abs(point.price - fmean(item.price for item in cluster)) <= tolerance
            ),
            None,
        )
        if matching is None:
            clusters.append([point])
        else:
            matching.append(point)
    return clusters


def _fair_value_gaps(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
) -> list[AnalysisZone]:
    result: list[AnalysisZone] = []
    for index in range(max(2, len(candles) - 120), len(candles)):
        first = candles[index - 2]
        third = candles[index]
        if third.low > first.high and third.low - first.high >= current_atr * 0.08:
            lower, upper = first.high, third.low
            filled = any(candle.low <= lower for candle in candles[index + 1 :])
            if not filled:
                result.append(
                    _gap_zone(
                        timeframe,
                        ZoneKind.BULLISH_FVG,
                        index,
                        candles,
                        lower,
                        upper,
                    )
                )
        if third.high < first.low and first.low - third.high >= current_atr * 0.08:
            lower, upper = third.high, first.low
            filled = any(candle.high >= upper for candle in candles[index + 1 :])
            if not filled:
                result.append(
                    _gap_zone(
                        timeframe,
                        ZoneKind.BEARISH_FVG,
                        index,
                        candles,
                        lower,
                        upper,
                    )
                )
    return result[-6:]


def _gap_zone(
    timeframe: str,
    kind: ZoneKind,
    index: int,
    candles: list[Candle],
    lower: float,
    upper: float,
) -> AnalysisZone:
    return AnalysisZone(
        id=f"{timeframe}-{kind}-{int(candles[index].start_time.timestamp())}",
        timeframe=timeframe,
        kind=kind,
        lower=lower,
        upper=upper,
        start_time=candles[index - 2].start_time,
        end_time=candles[-1].start_time,
        status="active",
        strength="medium",
        touches=1,
        rationale="Three-candle imbalance remains not fully traded through.",
    )


def _order_blocks(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
) -> list[AnalysisZone]:
    zones = []
    for direction in ("bullish", "bearish"):
        for index in range(len(candles) - 1, max(10, len(candles) - 80), -1):
            previous = candles[index - 10 : index]
            candle = candles[index]
            bullish_break = candle.close > max(item.high for item in previous)
            bearish_break = candle.close < min(item.low for item in previous)
            if (direction == "bullish" and not bullish_break) or (
                direction == "bearish" and not bearish_break
            ):
                continue
            opposite = next(
                (
                    item
                    for item in reversed(candles[max(0, index - 6) : index])
                    if (
                        direction == "bullish"
                        and item.close < item.open
                        or direction == "bearish"
                        and item.close > item.open
                    )
                ),
                None,
            )
            if opposite is None:
                continue
            kind = (
                ZoneKind.BULLISH_ORDER_BLOCK
                if direction == "bullish"
                else ZoneKind.BEARISH_ORDER_BLOCK
            )
            lower = opposite.low if direction == "bullish" else min(opposite.open, opposite.close)
            upper = max(opposite.open, opposite.close) if direction == "bullish" else opposite.high
            if upper - lower > current_atr * 2:
                continue
            zones.append(
                AnalysisZone(
                    id=f"{timeframe}-{kind}-{int(opposite.start_time.timestamp())}",
                    timeframe=timeframe,
                    kind=kind,
                    lower=lower,
                    upper=upper,
                    start_time=opposite.start_time,
                    end_time=candles[-1].start_time,
                    status="inferred",
                    strength="medium",
                    touches=1,
                    rationale=(
                        "Last opposite candle before a local range break; treated as inferred, "
                        "not confirmed institutional positioning."
                    ),
                )
            )
            break
    return zones


def _trend_lines(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
    highs: list[SwingPoint],
    lows: list[SwingPoint],
) -> list[AnalysisTrendLine]:
    end_time = candles[-1].start_time
    result: list[AnalysisTrendLine] = []
    for kind, points, ascending in (
        ("rising_support", lows, True),
        ("falling_resistance", highs, False),
    ):
        fit = _fit_trend_line(points, current_atr, ascending=ascending)
        if fit is None:
            continue
        anchor, slope = fit
        end_price = anchor.price + slope * (end_time - anchor.time).total_seconds()
        if end_price <= 0:
            continue
        result.append(
            AnalysisTrendLine(
                id=f"{timeframe}-{kind.replace('_', '-')}",
                timeframe=timeframe,
                kind=kind,
                start_time=anchor.time,
                start_price=anchor.price,
                end_time=end_time,
                end_price=end_price,
            )
        )
    return result


def _fit_trend_line(
    points: list[SwingPoint],
    current_atr: float,
    *,
    ascending: bool,
) -> tuple[SwingPoint, float] | None:
    """Best multi-touch support (ascending) or resistance (descending) line.

    Searches lines through two swing points and keeps the one the most other
    swings touch without piercing it, favouring more touches then a longer span.
    A single recent higher-low pair still qualifies (two touches); three or more
    touches simply rank higher.
    """

    tolerance = max(current_atr * 0.6, 1e-9)
    best: tuple[tuple[int, float], SwingPoint, float] | None = None
    count = len(points)
    for i in range(count):
        for j in range(i + 1, count):
            first, second = points[i], points[j]
            duration = (second.time - first.time).total_seconds()
            if duration <= 0:
                continue
            if ascending and second.price <= first.price:
                continue
            if not ascending and second.price >= first.price:
                continue
            slope = (second.price - first.price) / duration
            touches = 0
            valid = True
            for point in points[i:]:
                line_price = first.price + slope * (point.time - first.time).total_seconds()
                diff = point.price - line_price
                if (ascending and diff < -tolerance) or (not ascending and diff > tolerance):
                    valid = False
                    break
                if abs(diff) <= tolerance:
                    touches += 1
            if not valid or touches < 2:
                continue
            score = (touches, duration)
            if best is None or score > best[0]:
                best = (score, first, slope)
    if best is None:
        return None
    return best[1], best[2]


def _deduplicate_zones(zones: list[AnalysisZone], current_price: float) -> list[AnalysisZone]:
    grouped: dict[tuple[str, ZoneKind], list[AnalysisZone]] = defaultdict(list)
    for zone in zones:
        grouped[(zone.timeframe, zone.kind)].append(zone)
    selected = []
    for group in grouped.values():
        group.sort(
            key=lambda zone: (
                abs((zone.lower + zone.upper) / 2 - current_price),
                -TIMEFRAME_WEIGHT.get(zone.timeframe, 0),
            )
        )
        selected.extend(group[:4])
    selected.sort(
        key=lambda zone: (
            -TIMEFRAME_WEIGHT.get(zone.timeframe, 0),
            abs((zone.lower + zone.upper) / 2 - current_price),
        )
    )
    return selected


FLAG_POLE_ATR = 3.5
FLAG_MIN_POLE_BARS = 3
FLAG_MAX_POLE_BARS = 12
FLAG_MIN_BARS = 3
FLAG_MAX_BARS = 18
FLAG_RANGE_FRAC = 0.5
FLAG_POLE_EFFICIENCY = 0.6
FLAG_RETRACE_FRAC = 0.5


def _flag_patterns(
    candles: list[Candle],
    timeframe: str,
    current_atr: float,
) -> list[FlagPattern]:
    """Detect a current pole-and-flag continuation anchored to the latest bar.

    Deterministic and deliberately conservative: a strong impulse (the pole)
    followed by a tight consolidation that holds the move (the flag). It will
    miss flags a human eye accepts loosely; that is the intended trade-off.
    """

    n = len(candles)
    if current_atr <= 0 or n < FLAG_MIN_POLE_BARS + FLAG_MIN_BARS + 1:
        return []

    best: tuple[float, FlagPattern] | None = None
    for flag_bars in range(FLAG_MIN_BARS, FLAG_MAX_BARS + 1):
        if flag_bars >= n - FLAG_MIN_POLE_BARS:
            break
        flag = candles[n - flag_bars :]
        flag_high = max(item.high for item in flag)
        flag_low = min(item.low for item in flag)
        flag_range = flag_high - flag_low
        if flag_range <= 0:
            continue
        for pole_bars in range(FLAG_MIN_POLE_BARS, FLAG_MAX_POLE_BARS + 1):
            start = n - flag_bars - pole_bars
            if start < 1:
                continue
            pole = candles[start : n - flag_bars]
            base = candles[start - 1].close
            pole_end = pole[-1].close
            pole_height = abs(pole_end - base)
            if pole_height < FLAG_POLE_ATR * current_atr:
                continue
            points = [base, *(item.close for item in pole)]
            gross = sum(abs(points[i + 1] - points[i]) for i in range(len(points) - 1))
            if gross <= 0 or pole_height / gross < FLAG_POLE_EFFICIENCY:
                continue
            if flag_range > FLAG_RANGE_FRAC * pole_height:
                continue
            direction = "bull" if pole_end > base else "bear"
            if direction == "bull":
                if flag_low < pole_end - FLAG_RETRACE_FRAC * pole_height:
                    continue
                if flag_high > pole_end + 0.4 * pole_height:
                    continue
            else:
                if flag_high > pole_end + FLAG_RETRACE_FRAC * pole_height:
                    continue
                if flag_low < pole_end - 0.4 * pole_height:
                    continue
            score = pole_height / current_atr - flag_range / pole_height
            if best is not None and score <= best[0]:
                continue
            prior = flag[:-1]
            if direction == "bull":
                broke = bool(prior) and flag[-1].close > max(item.high for item in prior)
            else:
                broke = bool(prior) and flag[-1].close < min(item.low for item in prior)
            best = (
                score,
                FlagPattern(
                    timeframe=timeframe,
                    direction=direction,
                    status="breakout" if broke else "forming",
                    pole_start_time=pole[0].start_time,
                    pole_start_price=base,
                    pole_end_time=pole[-1].start_time,
                    pole_end_price=pole_end,
                    flag_start_time=flag[0].start_time,
                    flag_end_time=flag[-1].start_time,
                    flag_upper=flag_high,
                    flag_lower=flag_low,
                    rationale=(
                        f"{pole_height / current_atr:.1f} ATR pole over {pole_bars} bars, "
                        f"{flag_bars}-bar consolidation within "
                        f"{flag_range / pole_height * 100:.0f}% of the pole"
                    ),
                ),
            )
    return [best[1]] if best else []


def _build_scenarios(
    current_price: float,
    structures: list[TimeframeStructure],
    zones: list[AnalysisZone],
) -> list[TradeScenario]:
    structure_by_timeframe = {item.timeframe: item for item in structures}
    reference_atr = structure_by_timeframe.get("15", structures[-1]).atr
    return [
        _scenario(
            "long",
            current_price,
            reference_atr,
            structure_by_timeframe,
            zones,
        ),
        _scenario(
            "short",
            current_price,
            reference_atr,
            structure_by_timeframe,
            zones,
        ),
    ]


def _scenario(
    direction: str,
    current_price: float,
    reference_atr: float,
    structures: dict[str, TimeframeStructure],
    zones: list[AnalysisZone],
) -> TradeScenario:
    long = direction == "long"
    supportive_kinds = (
        {
            ZoneKind.SUPPORT,
            ZoneKind.BULLISH_FVG,
            ZoneKind.BULLISH_ORDER_BLOCK,
            ZoneKind.LIQUIDITY_LOW,
        }
        if long
        else {
            ZoneKind.RESISTANCE,
            ZoneKind.BEARISH_FVG,
            ZoneKind.BEARISH_ORDER_BLOCK,
            ZoneKind.LIQUIDITY_HIGH,
        }
    )
    target_kinds = (
        {ZoneKind.RESISTANCE, ZoneKind.LIQUIDITY_HIGH, ZoneKind.BEARISH_FVG}
        if long
        else {ZoneKind.SUPPORT, ZoneKind.LIQUIDITY_LOW, ZoneKind.BULLISH_FVG}
    )
    candidates = [
        zone
        for zone in zones
        if zone.kind in supportive_kinds
        and (
            zone.lower <= current_price + reference_atr * 0.35
            if long
            else zone.upper >= current_price - reference_atr * 0.35
        )
    ]
    candidates.sort(
        key=lambda zone: (
            abs((zone.lower + zone.upper) / 2 - current_price),
            -TIMEFRAME_WEIGHT.get(zone.timeframe, 0),
        )
    )
    entry_source = candidates[0] if candidates else None
    if entry_source:
        entry = PriceZone(lower=entry_source.lower, upper=entry_source.upper)
    else:
        entry = PriceZone(
            lower=max(current_price - reference_atr * 0.25, 1e-12),
            upper=current_price + reference_atr * 0.25,
        )
    invalidation = (
        max(entry.lower - reference_atr * 0.35, 1e-12)
        if long
        else entry.upper + reference_atr * 0.35
    )
    entry_mid = (entry.lower + entry.upper) / 2
    risk = abs(entry_mid - invalidation)
    target_zones = [
        zone
        for zone in zones
        if zone.kind in target_kinds
        and (zone.lower > entry_mid if long else zone.upper < entry_mid)
    ]
    target_zones.sort(key=lambda zone: abs((zone.lower + zone.upper) / 2 - entry_mid))
    target_prices = [(zone.lower if long else zone.upper) for zone in target_zones[:3]]
    for multiple in (1.5, 2.5, 4.0):
        if len(target_prices) >= 3:
            break
        target_prices.append(entry_mid + (risk * multiple if long else -risk * multiple))
    unique_targets = []
    for target in target_prices:
        if target <= 0 or any(abs(target - existing) < risk * 0.1 for existing in unique_targets):
            continue
        unique_targets.append(target)
    targets = [
        ScenarioTarget(
            label=f"TP{index}",
            price=target,
            reward_risk=round(abs(target - entry_mid) / risk, 2),
        )
        for index, target in enumerate(unique_targets[:3], start=1)
        if risk > 0
    ]

    expected_bias = MarketBias.BULLISH if long else MarketBias.BEARISH
    opposing_bias = MarketBias.BEARISH if long else MarketBias.BULLISH
    aligned = [
        timeframe
        for timeframe in ("240", "60", "15")
        if structures.get(timeframe) and structures[timeframe].bias == expected_bias
    ]
    opposed = [
        timeframe
        for timeframe in ("240", "60", "15")
        if structures.get(timeframe) and structures[timeframe].bias == opposing_bias
    ]
    evidence = [f"{timeframe} structure is {expected_bias}." for timeframe in aligned]
    if entry_source:
        evidence.append(f"Entry references {entry_source.timeframe} {entry_source.kind}.")
    conflicts = [f"{timeframe} structure is {opposing_bias}." for timeframe in opposed]
    if not entry_source:
        conflicts.append("No nearby active structural zone supports the entry.")
    status = (
        "primary"
        if len(aligned) >= 2 and "60" in aligned and "15" in aligned
        else "alternative"
        if aligned
        else "watch"
    )
    quality = (
        "high"
        if len(evidence) >= 4 and not conflicts
        else "medium"
        if len(evidence) >= 2 and len(conflicts) <= 1
        else "low"
    )
    trigger = (
        "Wait for a 5m rejection and a close back above the entry zone."
        if long
        else "Wait for a 5m rejection and a close back below the entry zone."
    )
    return TradeScenario(
        direction=direction,
        status=status,
        quality=quality,
        entry_zone=entry,
        trigger=trigger,
        invalidation_price=invalidation,
        targets=targets,
        evidence=evidence,
        conflicts=conflicts,
    )


def _preferred_direction(scenarios: list[TradeScenario]) -> str:
    primary = [scenario for scenario in scenarios if scenario.status == "primary"]
    if len(primary) == 1:
        return primary[0].direction
    medium_or_high = [
        scenario
        for scenario in scenarios
        if scenario.quality in {"medium", "high"} and scenario.status != "watch"
    ]
    return medium_or_high[0].direction if len(medium_or_high) == 1 else "neutral"


def _decision(preferred: str, scenarios: list[TradeScenario]) -> str:
    if preferred == "neutral":
        return "No clear directional edge. Keep both scenarios conditional and wait."
    scenario = next(item for item in scenarios if item.direction == preferred)
    return (
        f"{preferred.capitalize()} context is preferred, but entry is valid only after: "
        f"{scenario.trigger}"
    )
