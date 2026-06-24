import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from trade3_api.ai_models import AiReviewStatus, AiVerdict
from trade3_api.market_analysis import analyze_market_snapshot
from trade3_api.market_models import Candle
from trade3_api.ollama_analysis import OllamaMarketAnalyst


def snapshot():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = {}
    for interval, minutes in {"5": 5, "15": 15, "60": 60, "240": 240}.items():
        candles[interval] = [
            Candle(
                start_time=start + timedelta(minutes=minutes * index),
                open=100 + index * 0.1,
                high=101 + index * 0.1,
                low=99 + index * 0.1,
                close=100.5 + index * 0.1,
                volume=100 + index,
                turnover_usdt=10_000 + index,
                is_closed=True,
            )
            for index in range(100)
        ]
    return analyze_market_snapshot(symbol="BTCUSDT", candles_by_interval=candles)


@pytest.mark.asyncio
async def test_ollama_review_is_structured_and_cached() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        body = json.loads(request.content)
        assert body["think"] is False
        assert body["format"]["properties"]["verdict"]
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        "observed_biases": {
                            "h4": "insufficient",
                            "h1": "insufficient",
                            "m15": "insufficient",
                            "m5": "insufficient",
                        },
                        "verdict": "long_candidate",
                        "conviction": "medium",
                        "summary_code": "aligned_long",
                        "supporting_fact_ids": ["long_quality_low"],
                        "counter_fact_ids": [],
                        "wait_condition_ids": ["long_trigger"],
                    },
                    ensure_ascii=False,
                )
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:11434",
    )
    analyst = OllamaMarketAnalyst(
        base_url="http://127.0.0.1:11434",
        model="test-model",
        client=client,
    )

    first = await analyst.review(snapshot())
    second = await analyst.review(snapshot())

    assert first.status == AiReviewStatus.READY
    assert first.verdict == AiVerdict.LONG_CANDIDATE
    assert second == first
    assert requests == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_ollama_response_is_rejected_after_retry() -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"response": "not-json"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:11434",
    )
    analyst = OllamaMarketAnalyst(
        base_url="http://127.0.0.1:11434",
        model="test-model",
        client=client,
    )

    review = await analyst.review(snapshot())

    # Ollama answered, so this is a rejected review, not an offline one, and the
    # analyst retried once before giving up.
    assert review.status == AiReviewStatus.REJECTED
    assert requests == 2
    assert review.verdict == AiVerdict.WAIT
    assert review.advisory_only is True
    await client.aclose()


@pytest.mark.asyncio
async def test_connection_error_is_reported_as_offline() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:11434",
    )
    analyst = OllamaMarketAnalyst(
        base_url="http://127.0.0.1:11434",
        model="test-model",
        client=client,
    )

    review = await analyst.review(snapshot())

    assert review.status == AiReviewStatus.UNAVAILABLE
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_observed_biases_are_coerced_not_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "response": json.dumps(
                    {
                        # Deliberately wrong biases — should be coerced, not rejected.
                        "observed_biases": {
                            "h4": "bullish",
                            "h1": "bearish",
                            "m15": "range",
                            "m5": "bullish",
                        },
                        "verdict": "wait",
                        "conviction": "low",
                        "summary_code": "no_edge",
                        "supporting_fact_ids": [],
                        "counter_fact_ids": [],
                        "wait_condition_ids": ["timeframe_alignment"],
                    },
                    ensure_ascii=False,
                )
            },
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:11434",
    )
    analyst = OllamaMarketAnalyst(
        base_url="http://127.0.0.1:11434",
        model="test-model",
        client=client,
    )

    snap = snapshot()
    review = await analyst.review(snap)

    assert review.status == AiReviewStatus.READY
    expected = {item.timeframe: item.bias for item in snap.structures}
    assert review.observed_biases.h4 == expected["240"]
    assert review.observed_biases.m5 == expected["5"]
    await client.aclose()


def test_ollama_rejects_non_loopback_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaMarketAnalyst(base_url="https://example.com", model="test-model")
