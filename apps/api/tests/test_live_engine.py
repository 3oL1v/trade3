from typing import Any, cast

import pytest

from trade3_api.live_engine import LiveMarketEngine
from trade3_api.live_store import LiveMarketStore


def build_engine() -> LiveMarketEngine:
    return LiveMarketEngine(
        client=cast(Any, object()),
        scanner=cast(Any, object()),
        store=LiveMarketStore(),
        ws_url="wss://example.test",
        universe_size=20,
        candle_limit=300,
        universe_refresh_seconds=3600,
        max_backfill_concurrency=4,
        max_message_age_seconds=30,
        max_clock_skew_seconds=5,
        max_candidate_spread_bps=5,
    )


def test_successful_reconnect_clears_only_stream_error() -> None:
    engine = build_engine()

    engine._on_reconnect("no close frame received or sent")
    assert engine._reconnect_count == 1
    assert engine._current_error() == "no close frame received or sent"

    engine._journal_error = "journal: database busy"
    engine._on_stream_connected()

    assert engine._current_error() == "journal: database busy"


def test_error_priority_preserves_the_most_actionable_failure() -> None:
    engine = build_engine()
    engine._stream_error = "temporary websocket failure"
    engine._journal_error = "journal: database busy"
    engine._engine_error = "universe refresh failed"

    assert engine._current_error() == "universe refresh failed"

    engine._engine_error = None
    assert engine._current_error() == "journal: database busy"

    engine._journal_error = None
    assert engine._current_error() == "temporary websocket failure"


@pytest.mark.asyncio
async def test_status_exposes_disabled_legacy_journal() -> None:
    status = await build_engine().status()

    assert status.journal_enabled is False
