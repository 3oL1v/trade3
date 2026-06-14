import asyncio
from datetime import UTC, datetime
from typing import Callable, Protocol

from .market_models import (
    LinearInstrument,
    LinearTicker,
    MarketCandidate,
    MarketUniverse,
    UniverseCriteria,
)

DEFAULT_EXCLUDED_BASE_COINS = {
    "USDC",
    "USDE",
    "USDD",
    "DAI",
    "FDUSD",
    "TUSD",
    "PYUSD",
    "XAG",
    "XAU",
    "XAUT",
    "PAXG",
}


class MarketDataProvider(Protocol):
    async def get_usdt_perpetual_instruments(self) -> list[LinearInstrument]: ...

    async def get_linear_tickers(self) -> tuple[list[LinearTicker], datetime]: ...


class MarketDataStaleError(RuntimeError):
    pass


class MarketScanner:
    def __init__(
        self,
        client: MarketDataProvider,
        max_spread_bps: float,
        min_turnover_24h_usdt: float,
        min_open_interest_usdt: float,
        min_listing_age_days: int = 30,
        max_abs_funding_rate_pct: float = 0.10,
        max_abs_price_change_24h_pct: float = 15,
        max_source_age_seconds: float = 120,
        allowed_base_coins: set[str] | None = None,
        excluded_base_coins: set[str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._max_spread_bps = max_spread_bps
        self._min_turnover = min_turnover_24h_usdt
        self._min_open_interest = min_open_interest_usdt
        self._min_listing_age_days = min_listing_age_days
        self._max_abs_funding_rate_pct = max_abs_funding_rate_pct
        self._max_abs_price_change_24h_pct = max_abs_price_change_24h_pct
        self._max_source_age_seconds = max_source_age_seconds
        self._allowed_base_coins = allowed_base_coins
        self._excluded_base_coins = (
            DEFAULT_EXCLUDED_BASE_COINS if excluded_base_coins is None else excluded_base_coins
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    async def top_markets(self, limit: int) -> MarketUniverse:
        instruments, ticker_result = await _gather_market_data(self._client)
        tickers, source_time = ticker_result
        source_age_seconds = (self._clock() - source_time).total_seconds()
        if abs(source_age_seconds) > self._max_source_age_seconds:
            raise MarketDataStaleError(
                f"Bybit ticker data timestamp differs from local UTC by "
                f"{source_age_seconds:.1f} seconds"
            )
        instrument_by_symbol = {item.symbol: item for item in instruments}
        candidates: list[MarketCandidate] = []

        for ticker in tickers:
            instrument = instrument_by_symbol.get(ticker.symbol)
            if instrument is None or instrument.base_coin in self._excluded_base_coins:
                continue
            if (
                self._allowed_base_coins is not None
                and instrument.base_coin not in self._allowed_base_coins
            ):
                continue
            listing_age_days = max((source_time - instrument.launch_time).days, 0)
            funding_rate_pct = ticker.funding_rate * 100
            if (
                ticker.last_price <= 0
                or ticker.bid_price <= 0
                or ticker.ask_price <= ticker.bid_price
                or listing_age_days < self._min_listing_age_days
                or abs(funding_rate_pct) > self._max_abs_funding_rate_pct
                or abs(ticker.price_change_24h_pct) > self._max_abs_price_change_24h_pct
            ):
                continue
            midpoint = (ticker.bid_price + ticker.ask_price) / 2
            spread_bps = (ticker.ask_price - ticker.bid_price) / midpoint * 10_000
            if (
                spread_bps > self._max_spread_bps
                or ticker.turnover_24h_usdt < self._min_turnover
                or ticker.open_interest_usdt < self._min_open_interest
            ):
                continue
            candidates.append(
                MarketCandidate(
                    rank=1,
                    symbol=ticker.symbol,
                    base_coin=instrument.base_coin,
                    last_price=ticker.last_price,
                    turnover_24h_usdt=ticker.turnover_24h_usdt,
                    open_interest_usdt=ticker.open_interest_usdt,
                    spread_bps=round(spread_bps, 4),
                    funding_rate_pct=round(funding_rate_pct, 6),
                    price_change_24h_pct=round(ticker.price_change_24h_pct, 4),
                    launch_time=instrument.launch_time,
                    listing_age_days=listing_age_days,
                    tick_size=instrument.tick_size,
                )
            )

        candidates.sort(key=lambda item: item.turnover_24h_usdt, reverse=True)
        selected = candidates[:limit]
        for rank, candidate in enumerate(selected, start=1):
            candidate.rank = rank

        return MarketUniverse(
            generated_at=self._clock(),
            source_time=source_time,
            requested_limit=limit,
            eligible_count=len(candidates),
            rejected_count=max(len(tickers) - len(candidates), 0),
            criteria=UniverseCriteria(
                max_spread_bps=self._max_spread_bps,
                min_turnover_24h_usdt=self._min_turnover,
                min_open_interest_usdt=self._min_open_interest,
                min_listing_age_days=self._min_listing_age_days,
                max_abs_funding_rate_pct=self._max_abs_funding_rate_pct,
                max_abs_price_change_24h_pct=self._max_abs_price_change_24h_pct,
                allowed_base_coins=sorted(self._allowed_base_coins or []),
                excluded_base_coins=sorted(self._excluded_base_coins),
            ),
            markets=selected,
        )


async def _gather_market_data(
    client: MarketDataProvider,
) -> tuple[list[LinearInstrument], tuple[list[LinearTicker], datetime]]:
    return await asyncio.gather(
        client.get_usdt_perpetual_instruments(),
        client.get_linear_tickers(),
    )
