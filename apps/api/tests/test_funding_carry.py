from datetime import UTC, datetime, timedelta

import pytest

from trade3_api.funding_carry import (
    annualized_apr_pct,
    breakeven_hours,
    build_carry_board,
)
from trade3_api.market_models import LinearInstrument, LinearTicker


def test_annualized_apr_scales_with_interval() -> None:
    # 0.01% every 8h over a year: 0.01 * (8760 / 8) = 10.95%
    assert annualized_apr_pct(0.01, 8) == 10.95
    # Same rate paid twice as often (4h) doubles the APR.
    assert annualized_apr_pct(0.01, 4) == 21.9


def test_breakeven_hours_covers_round_trip_fees() -> None:
    # 0.22% round trip / 0.01% per interval = 22 intervals * 8h = 176h.
    assert breakeven_hours(0.01, 8, 0.22) == 176.0
    assert breakeven_hours(0.0, 8, 0.22) is None


def _instrument(symbol: str, base_coin: str, interval: int = 480) -> LinearInstrument:
    return LinearInstrument(
        symbol=symbol,
        base_coin=base_coin,
        contract_type="LinearPerpetual",
        status="Trading",
        quote_coin="USDT",
        settle_coin="USDT",
        is_pre_listing=False,
        launch_time=datetime(2021, 1, 1, tzinfo=UTC),
        tick_size=0.01,
        funding_interval_minutes=interval,
    )


def _ticker(symbol: str, funding_rate: float, turnover: float = 50_000_000) -> LinearTicker:
    return LinearTicker(
        symbol=symbol,
        last_price=100.0,
        turnover_24h_usdt=turnover,
        volume_24h=1_000,
        open_interest_usdt=20_000_000,
        bid_price=99.99,
        ask_price=100.01,
        funding_rate=funding_rate,
        price_change_24h_pct=2.0,
    )


class FakeClient:
    def __init__(self) -> None:
        self.history_calls: list[str] = []

    async def get_usdt_perpetual_instruments(self) -> list[LinearInstrument]:
        return [
            _instrument("HOTUSDT", "HOT"),
            _instrument("MIDUSDT", "MID"),
            _instrument("NEGUSDT", "NEG"),
            _instrument("USDCUSDT", "USDC"),  # excluded base coin
            _instrument("THINUSDT", "THIN"),  # filtered on turnover
        ]

    async def get_linear_tickers(self) -> tuple[list[LinearTicker], datetime]:
        tickers = [
            _ticker("HOTUSDT", 0.0005),  # +0.05% -> hottest carry
            _ticker("MIDUSDT", 0.0001),  # +0.01%
            _ticker("NEGUSDT", -0.0003),  # negative -> long perp + short spot
            _ticker("USDCUSDT", 0.0008),  # excluded despite huge funding
            _ticker("THINUSDT", 0.0009, turnover=1_000),  # too illiquid
        ]
        return tickers, datetime(2026, 6, 24, 12, 0, tzinfo=UTC)

    async def get_funding_history(
        self, symbol: str, limit: int = 200
    ) -> list[tuple[datetime, float]]:
        self.history_calls.append(symbol)
        start = datetime(2026, 6, 20, tzinfo=UTC)
        # Persistent positive funding for HOT, mixed for the rest.
        rate = 0.0005 if symbol == "HOTUSDT" else 0.0001
        return [(start + timedelta(hours=8 * i), rate) for i in range(limit)]


@pytest.mark.asyncio
async def test_carry_board_ranks_by_apr_and_ignores_funding_cap() -> None:
    client = FakeClient()
    board = await build_carry_board(client, limit=10, with_history=False)

    symbols = [item.symbol for item in board.opportunities]
    # Stablecoin excluded, illiquid dropped; the rest ranked by |APR| desc.
    assert symbols == ["HOTUSDT", "NEGUSDT", "MIDUSDT"]
    assert board.eligible_count == 3
    assert board.round_trip_fee_pct == pytest.approx(0.22)

    hot = board.opportunities[0]
    assert hot.side == "short_perp_long_spot"
    assert hot.easily_hedgeable is True
    assert hot.annualized_apr_pct == pytest.approx(54.75)  # 0.05% * (8760/8)

    neg = next(item for item in board.opportunities if item.symbol == "NEGUSDT")
    assert neg.side == "long_perp_short_spot"
    assert neg.easily_hedgeable is False


@pytest.mark.asyncio
async def test_carry_board_attaches_funding_history() -> None:
    client = FakeClient()
    board = await build_carry_board(client, limit=10, with_history=True)

    hot = board.opportunities[0]
    assert hot.history_samples > 0
    assert hot.positive_fraction == 1.0
    assert hot.mean_funding_rate_pct == pytest.approx(0.05)
    assert "HOTUSDT" in client.history_calls
