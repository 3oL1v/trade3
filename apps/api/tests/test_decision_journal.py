from datetime import UTC, datetime
from pathlib import Path

import pytest

from trade3_api.decision_journal import ManualDecisionJournal, agreement_with_ai
from trade3_api.decision_models import (
    DecisionAction,
    DecisionDirection,
    ManualDecisionRequest,
)


def request(
    *,
    action: DecisionAction = DecisionAction.ACCEPT,
    direction: DecisionDirection = DecisionDirection.LONG,
    ai_verdict: str | None = "long_candidate",
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
async def test_journal_releases_sqlite_file_handles(tmp_path) -> None:
    database = Path(tmp_path) / "decisions.sqlite3"
    journal = ManualDecisionJournal(str(database))
    await journal.initialize()
    await journal.list_decisions()

    database.unlink()

    assert not database.exists()
