from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trade3_api.market_models import Candle
from trade3_api.trade_plan import _rounded_positive, _targets, build_trend_pullback_plan


def candle(
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    interval_minutes: int = 5,
) -> Candle:
    return Candle(
        start_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=interval_minutes * index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100,
        turnover_usdt=10_000,
        is_closed=True,
    )


def long_pullback() -> list[Candle]:
    candles = []
    for index in range(70):
        price = 100 + index * 0.3
        candles.append(candle(index, price, price + 0.5, price - 0.4, price + 0.2))
    candles.extend(
        [
            candle(70, 119.0, 119.2, 117.9, 118.6),
            candle(71, 118.6, 119.5, 118.5, 119.4),
            candle(72, 119.4, 120.0, 119.2, 119.8),
        ]
    )
    return candles


def short_pullback() -> list[Candle]:
    candles = []
    for index in range(70):
        price = 140 - index * 0.3
        candles.append(candle(index, price, price + 0.4, price - 0.5, price - 0.2))
    candles.extend(
        [
            candle(70, 121.0, 122.1, 120.8, 121.4),
            candle(71, 121.4, 121.5, 120.5, 120.6),
            candle(72, 120.6, 120.8, 120.0, 120.2),
        ]
    )
    return candles


def context(direction: str, step: float = 0.5) -> list[Candle]:
    candles = []
    for index in range(60):
        price = 105 + index * step if direction == "long" else 135 - index * step
        candles.append(
            candle(
                index,
                price,
                price + (1.2 if direction == "long" else 0.8),
                price - (0.8 if direction == "long" else 1.2),
                price + (0.3 if direction == "long" else -0.3),
                15,
            )
        )
    return candles


def test_long_plan_places_stop_and_targets_on_correct_sides() -> None:
    plan = build_trend_pullback_plan(
        "long",
        long_pullback(),
        context("long"),
        live_price=119.5,
        tick_size=0.1,
        score_state="candidate",
    )

    assert plan is not None
    assert plan.status == "ready"
    assert plan.invalidation_price < plan.entry_zone.lower
    assert plan.structural_target is not None
    assert plan.structural_target > plan.entry_zone.upper
    assert all(target.price > plan.entry_zone.upper for target in plan.targets)
    assert plan.structural_reward_risk is not None
    assert plan.structural_reward_risk >= 1.5


def test_short_plan_places_stop_and_targets_on_correct_sides() -> None:
    plan = build_trend_pullback_plan(
        "short",
        short_pullback(),
        context("short"),
        live_price=120.5,
        tick_size=0.1,
        score_state="candidate",
    )

    assert plan is not None
    assert plan.status == "ready"
    assert plan.invalidation_price > plan.entry_zone.upper
    assert plan.structural_target is not None
    assert plan.structural_target < plan.entry_zone.lower
    assert all(target.price < plan.entry_zone.lower for target in plan.targets)


def test_targets_skip_reward_risk_that_rounds_to_zero() -> None:
    targets = _targets(
        direction="long",
        entry=100,
        risk=10,
        structural_target=100.001,
        tick_size=0.001,
    )

    assert all(target.reward_risk > 0 for target in targets)


def test_structural_reward_risk_that_rounds_to_zero_becomes_missing() -> None:
    assert _rounded_positive(0.004) is None
    assert _rounded_positive(0.006) == 0.01


def test_watch_score_cannot_produce_ready_plan() -> None:
    plan = build_trend_pullback_plan(
        "long",
        long_pullback(),
        context("long"),
        live_price=119.5,
        tick_size=0.1,
        score_state="watch",
    )

    assert plan is not None
    assert plan.status == "watch"
    assert any("score" in note.lower() for note in plan.notes)


def test_insufficient_structural_reward_blocks_plan() -> None:
    plan = build_trend_pullback_plan(
        "long",
        long_pullback(),
        context("long", step=0.25),
        live_price=119.5,
        tick_size=0.1,
        score_state="candidate",
    )

    assert plan is not None
    assert plan.status == "blocked"
    assert plan.structural_reward_risk is not None
    assert plan.structural_reward_risk < 1.5


def test_all_prices_are_rounded_to_exchange_tick() -> None:
    tick = Decimal("0.25")
    plan = build_trend_pullback_plan(
        "long",
        long_pullback(),
        context("long"),
        live_price=119.5,
        tick_size=float(tick),
        score_state="candidate",
    )

    assert plan is not None
    prices = [
        plan.pullback_zone.lower,
        plan.pullback_zone.upper,
        plan.trigger_price,
        plan.entry_zone.lower,
        plan.entry_zone.upper,
        plan.invalidation_price,
        *(target.price for target in plan.targets),
    ]
    assert all(Decimal(str(price)) % tick == 0 for price in prices)
