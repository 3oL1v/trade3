import asyncio
from datetime import UTC, datetime

from .bybit import BybitApiError
from .funding_carry_models import CarryBoard, CarryOpportunity
from .market_models import LinearInstrument, LinearTicker
from .scanner import DEFAULT_EXCLUDED_BASE_COINS

HOURS_PER_YEAR = 24 * 365


def annualized_apr_pct(funding_rate_pct: float, interval_hours: float) -> float:
    """Annualize a per-interval funding rate, assuming it persists."""

    if interval_hours <= 0:
        return 0.0
    return round(funding_rate_pct * (HOURS_PER_YEAR / interval_hours), 4)


def breakeven_hours(
    funding_rate_pct: float,
    interval_hours: float,
    round_trip_fee_pct: float,
) -> float | None:
    """Hours to hold the hedge for funding to cover the round-trip fees on both legs."""

    rate = abs(funding_rate_pct)
    if rate <= 0:
        return None
    intervals = round_trip_fee_pct / rate
    return round(intervals * interval_hours, 2)


def _side(funding_rate_pct: float) -> tuple[str, str, bool]:
    """Which side collects the funding, a human label, and whether it is the easy side."""

    if funding_rate_pct >= 0:
        # Longs pay shorts: be short the perp and long spot to stay neutral.
        return "short_perp_long_spot", "шорт perp + лонг спот", True
    # Shorts pay longs: be long the perp and short spot — spot short needs a borrow.
    return "long_perp_short_spot", "лонг perp + шорт спот", False


class _CarryProvider:
    async def get_usdt_perpetual_instruments(self) -> list[LinearInstrument]: ...

    async def get_linear_tickers(self) -> tuple[list[LinearTicker], datetime]: ...

    async def get_funding_history(
        self, symbol: str, limit: int = 200
    ) -> list[tuple[datetime, float]]: ...


async def build_carry_board(
    client: _CarryProvider,
    *,
    limit: int = 15,
    taker_fee_rate_pct: float = 0.055,
    min_turnover_24h_usdt: float = 15_000_000,
    min_open_interest_usdt: float = 5_000_000,
    max_spread_bps: float = 25,
    allowed_base_coins: set[str] | None = None,
    excluded_base_coins: set[str] | None = None,
    with_history: bool = True,
    history_intervals: int = 42,
    now: datetime | None = None,
) -> CarryBoard:
    excluded = DEFAULT_EXCLUDED_BASE_COINS if excluded_base_coins is None else excluded_base_coins
    round_trip_fee_pct = round(4 * taker_fee_rate_pct, 6)
    moment = now or datetime.now(UTC)

    instruments, (tickers, source_time) = await asyncio.gather(
        client.get_usdt_perpetual_instruments(),
        client.get_linear_tickers(),
    )
    instrument_by_symbol = {item.symbol: item for item in instruments}

    opportunities: list[CarryOpportunity] = []
    for ticker in tickers:
        instrument = instrument_by_symbol.get(ticker.symbol)
        if instrument is None or instrument.base_coin in excluded:
            continue
        if allowed_base_coins is not None and instrument.base_coin not in allowed_base_coins:
            continue
        if (
            ticker.last_price <= 0
            or ticker.bid_price <= 0
            or ticker.ask_price <= ticker.bid_price
            or ticker.turnover_24h_usdt < min_turnover_24h_usdt
            or ticker.open_interest_usdt < min_open_interest_usdt
        ):
            continue
        midpoint = (ticker.bid_price + ticker.ask_price) / 2
        spread_bps = (ticker.ask_price - ticker.bid_price) / midpoint * 10_000
        if spread_bps > max_spread_bps:
            continue

        funding_rate_pct = ticker.funding_rate * 100
        interval_hours = instrument.funding_interval_minutes / 60
        side, side_label, easily_hedgeable = _side(funding_rate_pct)
        opportunities.append(
            CarryOpportunity(
                symbol=ticker.symbol,
                base_coin=instrument.base_coin,
                last_price=ticker.last_price,
                funding_rate_pct=round(funding_rate_pct, 6),
                funding_interval_hours=round(interval_hours, 4),
                annualized_apr_pct=annualized_apr_pct(funding_rate_pct, interval_hours),
                side=side,
                side_label=side_label,
                easily_hedgeable=easily_hedgeable,
                breakeven_hours=breakeven_hours(
                    funding_rate_pct, interval_hours, round_trip_fee_pct
                ),
                turnover_24h_usdt=ticker.turnover_24h_usdt,
                open_interest_usdt=ticker.open_interest_usdt,
                mean_funding_rate_pct=None,
                positive_fraction=None,
                history_samples=0,
            )
        )

    eligible_count = len(opportunities)
    opportunities.sort(key=lambda item: abs(item.annualized_apr_pct), reverse=True)
    selected = opportunities[:limit]

    if with_history and selected:
        await _attach_history(client, selected, history_intervals)

    return CarryBoard(
        generated_at=moment,
        source_time=source_time,
        taker_fee_rate_pct=taker_fee_rate_pct,
        round_trip_fee_pct=round_trip_fee_pct,
        eligible_count=eligible_count,
        opportunities=selected,
    )


async def _attach_history(
    client: _CarryProvider,
    opportunities: list[CarryOpportunity],
    history_intervals: int,
) -> None:
    async def fetch(symbol: str) -> list[tuple[datetime, float]] | None:
        try:
            return await client.get_funding_history(symbol, limit=history_intervals)
        except (BybitApiError, ValueError, KeyError):
            return None

    histories = await asyncio.gather(*(fetch(item.symbol) for item in opportunities))
    for opportunity, history in zip(opportunities, histories, strict=True):
        if not history:
            continue
        rates = [rate for _, rate in history]
        same_sign = sum(
            1 for rate in rates if (rate >= 0) == (opportunity.funding_rate_pct >= 0)
        )
        opportunity.mean_funding_rate_pct = round(sum(rates) / len(rates) * 100, 6)
        opportunity.positive_fraction = round(same_sign / len(rates), 4)
        opportunity.history_samples = len(rates)
