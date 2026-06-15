from datetime import UTC, datetime
from pathlib import Path

import pytest

from trade3_api.decision_journal import (
    DecisionNotFoundError,
    ManualDecisionJournal,
    agreement_with_ai,
    forward_return_pct,
)
from trade3_api.decision_models import (
    DecisionAction,
    DecisionDirection,
    DecisionOutcomeRequest,
    ManualDecisionRequest,
)


def request(
    *,
    action: DecisionAction = DecisionAction.ACCEPT,
    direction: DecisionDirection = DecisionDirection.LONG,
    ai_verdict: str | None = "long_candidate",
    decision_price: float | None = 100.0,
    note: str | None = None,
    analysis_snapshot: dict | None = None,
    ai_review: dict | None = None,
) -> ManualDecisionRequest:
    return ManualDecisionRequest(
        symbol="BTCUSDT",
        action=action,
        direction=direction,
        ai_verdict=ai_verdict,
        ai_conviction="medium" if ai_verdict else None,
        decision_price=decision_price,
        snapshot_generated_at=datetime(2026, 6, 12, 10, 0, tzinfo=UTC),
        note=note,
        analysis_snapshot=analysis_snapshot,
        ai_review=ai_review,
    )


@pytest.mark.asyncio
async def test_record_and_list_roundtrip_preserves_snapshot(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    snapshot = {"symbol": "BTCUSDT", "bias": {"h1": "up"}, "levels": [1, 2, 3]}
    review = {"verdict": "long_candidate", "headline": "aligned trend"}

    recorded = await journal.record(
        request(note="clear pullback", analysis_snapshot=snapshot, ai_review=review),
        datetime(2026, 6, 12, 10, 5, tzinfo=UTC),
    )
    assert recorded.id == 1
    assert recorded.agreed_with_ai is True

    decisions = await journal.list_decisions()
    assert len(decisions) == 1
    stored = decisions[0]
    assert stored.symbol == "BTCUSDT"
    assert stored.action == DecisionAction.ACCEPT
    assert stored.direction == DecisionDirection.LONG
    assert stored.note == "clear pullback"
    assert stored.analysis_snapshot == snapshot
    assert stored.ai_review == review
    assert stored.snapshot_generated_at == datetime(2026, 6, 12, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_list_filters_by_action(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    now = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    await journal.record(request(action=DecisionAction.ACCEPT), now)
    await journal.record(
        request(action=DecisionAction.REJECT, direction=DecisionDirection.NONE, ai_verdict="wait"),
        now,
    )
    await journal.record(
        request(action=DecisionAction.DEFER, direction=DecisionDirection.NONE, ai_verdict="wait"),
        now,
    )

    rejected = await journal.list_decisions(action="reject")
    assert len(rejected) == 1
    assert rejected[0].action == DecisionAction.REJECT


@pytest.mark.asyncio
async def test_stats_counts_and_agreement_rate(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    now = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    # Agrees: AI said long, user accepted long.
    await journal.record(request(), now)
    # Disagrees: AI said wait, user accepted long anyway.
    await journal.record(request(ai_verdict="wait"), now)
    # Agrees: AI said wait, user rejected.
    await journal.record(
        request(action=DecisionAction.REJECT, direction=DecisionDirection.NONE, ai_verdict="wait"),
        now,
    )
    # No AI present: excluded from agreement.
    await journal.record(request(ai_verdict=None), now)

    stats = await journal.stats()
    assert stats.total == 4
    assert stats.accepted == 3
    assert stats.rejected == 1
    assert stats.longs == 3
    assert stats.accept_rate == 0.75
    assert stats.ai_comparable == 3
    assert stats.agreed_with_ai == 2
    assert stats.agreement_rate == pytest.approx(0.6667, abs=1e-4)


@pytest.mark.asyncio
async def test_agreement_is_none_without_ai_verdict() -> None:
    assert agreement_with_ai(DecisionAction.ACCEPT, DecisionDirection.LONG, None) is None
    assert agreement_with_ai(DecisionAction.ACCEPT, DecisionDirection.SHORT, "short_candidate")
    assert agreement_with_ai(DecisionAction.DEFER, DecisionDirection.NONE, "wait")
    assert agreement_with_ai(DecisionAction.ACCEPT, DecisionDirection.LONG, "wait") is False


@pytest.mark.asyncio
async def test_resolve_computes_directional_return_and_stats(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    now = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    long = await journal.record(request(decision_price=100.0), now)
    short = await journal.record(
        request(
            action=DecisionAction.ACCEPT,
            direction=DecisionDirection.SHORT,
            ai_verdict="short_candidate",
            decision_price=100.0,
        ),
        now,
    )

    resolved_long = await journal.resolve(
        long.id, DecisionOutcomeRequest(price=105.0), now
    )
    assert resolved_long.outcome_return_pct == pytest.approx(0.05)
    assert resolved_long.outcome_price == 105.0
    assert resolved_long.outcome_at is not None

    # Short call profits when price falls: +5% here.
    resolved_short = await journal.resolve(
        short.id, DecisionOutcomeRequest(price=95.0), now
    )
    assert resolved_short.outcome_return_pct == pytest.approx(0.05)

    stats = await journal.stats()
    assert stats.resolved == 2
    assert stats.accepts_resolved == 2
    assert stats.accept_win_rate == 1.0
    assert stats.average_accept_return_pct == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_resolve_computes_excess_over_benchmark(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    now = datetime(2026, 6, 12, 10, 5, tzinfo=UTC)

    # Long accept: +10% directional, BTC benchmark only +4% over the window.
    decision = await journal.record(
        request(decision_price=100.0), now, benchmark_symbol="BTCUSDT", benchmark_price=50_000.0
    )
    assert decision.benchmark_price == 50_000.0

    resolved = await journal.resolve(
        decision.id, DecisionOutcomeRequest(price=110.0), now, benchmark_price=52_000.0
    )
    assert resolved.outcome_return_pct == pytest.approx(0.10)
    assert resolved.benchmark_return_pct == pytest.approx(0.04)
    assert resolved.excess_return_pct == pytest.approx(0.06)

    stats = await journal.stats()
    assert stats.benchmark_resolved == 1
    assert stats.average_excess_return_pct == pytest.approx(0.06)
    assert stats.beat_benchmark_rate == 1.0


@pytest.mark.asyncio
async def test_resolve_missing_decision_raises(tmp_path) -> None:
    journal = ManualDecisionJournal(str(tmp_path / "decisions.sqlite3"))
    await journal.initialize()
    with pytest.raises(DecisionNotFoundError):
        await journal.resolve(
            999, DecisionOutcomeRequest(price=100.0), datetime(2026, 6, 12, tzinfo=UTC)
        )


def test_forward_return_handles_missing_decision_price() -> None:
    assert forward_return_pct(DecisionDirection.LONG, None, 100.0) is None
    assert forward_return_pct(DecisionDirection.LONG, 100.0, 110.0) == pytest.approx(0.1)
    assert forward_return_pct(DecisionDirection.SHORT, 100.0, 110.0) == pytest.approx(-0.1)


@pytest.mark.asyncio
async def test_journal_releases_sqlite_file_handles(tmp_path) -> None:
    database = Path(tmp_path) / "decisions.sqlite3"
    journal = ManualDecisionJournal(str(database))
    await journal.initialize()
    await journal.list_decisions()

    database.unlink()

    assert not database.exists()
