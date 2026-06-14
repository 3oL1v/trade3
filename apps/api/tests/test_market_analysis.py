import math
from datetime import UTC, datetime, timedelta

from trade3_api.analysis_models import MarketBias, ZoneKind
from trade3_api.market_analysis import analyze_market_snapshot
from trade3_api.market_models import Candle


def structured_candles(interval_minutes: int, count: int = 120) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = []
    for index in range(count):
        center = 100 + index * 0.16 + math.sin(index * 0.55) * 2.2
        open_price = center - 0.2
        close = center + 0.2
        candles.append(
            Candle(
                start_time=start + timedelta(minutes=interval_minutes * index),
                open=open_price,
                high=max(open_price, close) + 0.55,
                low=min(open_price, close) - 0.55,
                close=close,
                volume=100 + index,
                turnover_usdt=10_000 + index,
                is_closed=True,
            )
        )
    return candles


def test_snapshot_exposes_structure_zones_and_conditional_scenarios() -> None:
    candles = {
        interval: structured_candles(minutes)
        for interval, minutes in {"5": 5, "15": 15, "60": 60, "240": 240}.items()
    }

    snapshot = analyze_market_snapshot(
        symbol="BTCUSDT",
        candles_by_interval=candles,
    )

    assert len(snapshot.structures) == 4
    assert all(structure.bias == MarketBias.BULLISH for structure in snapshot.structures)
    assert {zone.kind for zone in snapshot.zones} >= {
        ZoneKind.SUPPORT,
        ZoneKind.RESISTANCE,
    }
    assert {scenario.direction for scenario in snapshot.scenarios} == {"long", "short"}
    assert snapshot.preferred_direction == "long"
    assert snapshot.scenarios[0].targets


def test_snapshot_detects_an_unfilled_bullish_fvg() -> None:
    base = structured_candles(15, 80)
    prior = base[-1]
    base.extend(
        [
            Candle(
                start_time=prior.start_time + timedelta(minutes=15),
                open=prior.close,
                high=prior.close + 0.4,
                low=prior.close - 0.4,
                close=prior.close + 0.2,
                volume=200,
                turnover_usdt=20_000,
                is_closed=True,
            ),
            Candle(
                start_time=prior.start_time + timedelta(minutes=30),
                open=prior.close + 1.0,
                high=prior.close + 2.5,
                low=prior.close + 0.8,
                close=prior.close + 2.2,
                volume=400,
                turnover_usdt=40_000,
                is_closed=True,
            ),
            Candle(
                start_time=prior.start_time + timedelta(minutes=45),
                open=prior.close + 2.6,
                high=prior.close + 3.1,
                low=prior.close + 1.2,
                close=prior.close + 2.8,
                volume=300,
                turnover_usdt=30_000,
                is_closed=True,
            ),
        ]
    )

    snapshot = analyze_market_snapshot(
        symbol="ETHUSDT",
        candles_by_interval={"15": base},
    )

    assert any(zone.kind == ZoneKind.BULLISH_FVG for zone in snapshot.zones)
