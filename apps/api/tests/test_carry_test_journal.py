from datetime import UTC, datetime, timedelta

import pytest

from trade3_api.carry_test_journal import (
    CarryTestJournal,
    annualize_pct,
    realized_carry_pct,
)
from trade3_api.carry_test_models import CarryPositionRequest


def test_realized_carry_sign_follows_side() -> None:
    # Short perp collects positive funding as-is.
    assert realized_carry_pct("short_perp_long_spot", 0.0006) == 0.06
    # Long perp collects negative funding, so the sign inverts to a gain.
    assert realized_carry_pct("long_perp_short_spot", -0.0006) == 0.06
    # Funding that flipped against the short shows up as a loss.
    assert realized_carry_pct("short_perp_long_spot", -0.0006) == -0.06


def test_annualize_scales_to_a_year() -> None:
    # 0.5% net over 48h -> 0.5 * (8760/48) = 91.25% APR
    assert annualize_pct(0.5, 48) == 91.25
    assert annualize_pct(0.5, 0) == 0.0


async def _journal(tmp_path) -> CarryTestJournal:
    journal = CarryTestJournal(str(tmp_path / "carry.sqlite3"))
    await journal.initialize()
    return journal


@pytest.mark.asyncio
async def test_only_matured_positions_are_due(tmp_path) -> None:
    journal = await _journal(tmp_path)
    now = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
    await journal.record(
        _request("BTCUSDT", "short_perp_long_spot"), now - timedelta(hours=50)
    )
    await journal.record(
        _request("ETHUSDT", "short_perp_long_spot"), now - timedelta(hours=10)
    )
    due = await journal.due_unresolved(horizon_hours=48, now=now)
    assert [p.symbol for p in due] == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_resolve_nets_fees_and_annualizes(tmp_path) -> None:
    journal = await _journal(tmp_path)
    opened = datetime(2026, 6, 24, 0, 0, tzinfo=UTC)
    resolved = opened + timedelta(hours=48)
    position = await journal.record(
        _request("BTCUSDT", "short_perp_long_spot", round_trip_fee_pct=0.22), opened
    )

    # Realized funding 0.30% over the window, fee 0.22% -> net 0.08%.
    updated = await journal.resolve(position.id, 0.30, 6, resolved)
    assert updated.realized_funding_pct == 0.30
    assert updated.net_carry_pct == pytest.approx(0.08)
    assert updated.funding_events == 6
    # 0.08% over 48h annualizes to 0.08 * (8760/48) = 14.6%
    assert updated.annualized_net_apr_pct == pytest.approx(14.6)


@pytest.mark.asyncio
async def test_stats_count_net_winners(tmp_path) -> None:
    journal = await _journal(tmp_path)
    opened = datetime(2026, 6, 24, 0, 0, tzinfo=UTC)
    resolved = opened + timedelta(hours=48)
    winner = await journal.record(
        _request("AAUSDT", "short_perp_long_spot", round_trip_fee_pct=0.22), opened
    )
    loser = await journal.record(
        _request("BBUSDT", "short_perp_long_spot", round_trip_fee_pct=0.22), opened
    )
    await journal.resolve(winner.id, 0.40, 6, resolved)  # net +0.18
    await journal.resolve(loser.id, 0.10, 6, resolved)  # net -0.12

    stats = await journal.stats(horizon_hours=48, now=resolved + timedelta(hours=1))
    assert stats.total == 2
    assert stats.resolved == 2
    assert stats.open_positions == 0
    assert stats.positive_after_fees == 1
    assert stats.win_rate_after_fees == 0.5
    assert stats.mean_net_carry_pct == pytest.approx(0.03)  # (0.18 - 0.12) / 2


def _request(
    symbol: str, side: str, round_trip_fee_pct: float = 0.22
) -> CarryPositionRequest:
    return CarryPositionRequest(
        symbol=symbol,
        side=side,
        entry_funding_rate_pct=0.05,
        entry_apr_pct=54.75,
        funding_interval_hours=8,
        round_trip_fee_pct=round_trip_fee_pct,
    )
