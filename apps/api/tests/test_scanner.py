from datetime import UTC, datetime

import pytest

from trade3_api.market_models import LinearInstrument, LinearTicker
from trade3_api.scanner import MarketDataStaleError, MarketScanner


class FakeClient:
    async def get_usdt_perpetual_instruments(self) -> list[LinearInstrument]:
        launch_time = datetime(2020, 1, 1, tzinfo=UTC)
        recent_launch_time = datetime(2025, 12, 15, tzinfo=UTC)
        return [
            LinearInstrument(
                symbol=symbol,
                base_coin=base_coin,
                contract_type="LinearPerpetual",
                status="Trading",
                quote_coin="USDT",
                settle_coin="USDT",
                is_pre_listing=False,
                launch_time=recent_launch_time if symbol == "NEWUSDT" else launch_time,
                tick_size=0.01,
            )
            for symbol, base_coin in [
                ("BTCUSDT", "BTC"),
                ("ETHUSDT", "ETH"),
                ("USDCUSDT", "USDC"),
                ("XAUUSDT", "XAU"),
                ("WIDEUSDT", "WIDE"),
                ("NEWUSDT", "NEW"),
                ("FUNDUSDT", "FUND"),
                ("HOTUSDT", "HOT"),
                ("NICHEUSDT", "NICHE"),
            ]
        ]

    async def get_linear_tickers(self) -> tuple[list[LinearTicker], datetime]:
        def ticker(
            symbol: str,
            turnover: float,
            bid: float,
            ask: float,
            funding_rate: float = 0.0001,
            price_change_24h_pct: float = 2,
        ) -> LinearTicker:
            return LinearTicker(
                symbol=symbol,
                last_price=(bid + ask) / 2,
                turnover_24h_usdt=turnover,
                volume_24h=1_000,
                open_interest_usdt=20_000_000,
                bid_price=bid,
                ask_price=ask,
                funding_rate=funding_rate,
                price_change_24h_pct=price_change_24h_pct,
            )

        return (
            [
                ticker("ETHUSDT", 400_000_000, 100, 100.01),
                ticker("BTCUSDT", 500_000_000, 100, 100.01),
                ticker("USDCUSDT", 600_000_000, 1, 1.0001),
                ticker("XAUUSDT", 650_000_000, 100, 100.01),
                ticker("WIDEUSDT", 700_000_000, 100, 101),
                ticker("NEWUSDT", 800_000_000, 100, 100.01),
                ticker("FUNDUSDT", 900_000_000, 100, 100.01, funding_rate=0.002),
                ticker("HOTUSDT", 1_000_000_000, 100, 100.01, price_change_24h_pct=24),
                ticker("NICHEUSDT", 950_000_000, 100, 100.01),
            ],
            datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_scanner_filters_and_ranks_by_turnover() -> None:
    current_time = datetime(2026, 1, 1, tzinfo=UTC)
    scanner = MarketScanner(
        client=FakeClient(),
        max_spread_bps=15,
        min_turnover_24h_usdt=25_000_000,
        min_open_interest_usdt=5_000_000,
        allowed_base_coins={"BTC", "ETH", "HOT"},
        clock=lambda: current_time,
    )

    result = await scanner.top_markets(limit=20)

    assert [market.symbol for market in result.markets] == ["BTCUSDT", "ETHUSDT"]
    assert [market.rank for market in result.markets] == [1, 2]
    assert result.eligible_count == 2
    assert all(market.listing_age_days > 30 for market in result.markets)
    assert result.criteria.max_abs_price_change_24h_pct == 15
    assert result.criteria.allowed_base_coins == ["BTC", "ETH", "HOT"]


@pytest.mark.asyncio
async def test_scanner_rejects_stale_ticker_snapshot() -> None:
    scanner = MarketScanner(
        client=FakeClient(),
        max_spread_bps=15,
        min_turnover_24h_usdt=25_000_000,
        min_open_interest_usdt=5_000_000,
        max_source_age_seconds=30,
        clock=lambda: datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
    )

    with pytest.raises(MarketDataStaleError, match="60.0 seconds"):
        await scanner.top_markets(limit=20)
