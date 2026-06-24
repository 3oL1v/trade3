import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, HTTPException, Path, Query, Request, Response

from .ai_models import AiMarketReview
from .analysis_models import MarketAnalysisSnapshot
from .auto_signal_collector import AutoSignalCollector
from .auto_signal_journal import AutoSignalJournal
from .auto_signal_models import AutoSignalList, AutoSignalStats
from .bybit import BybitApiError, BybitPublicClient, SUPPORTED_INTERVALS_MINUTES
from .carry_test_collector import CarryTestCollector
from .carry_test_journal import CarryTestJournal
from .carry_test_models import CarryPositionList, CarryTestStats
from .config import get_settings
from .decision_export import decisions_to_csv
from .funding_carry import build_carry_board
from .funding_carry_models import CarryBoard
from .decision_journal import DecisionNotFoundError, ManualDecisionJournal
from .decision_models import (
    DecisionOutcomeRequest,
    ManualDecision,
    ManualDecisionList,
    ManualDecisionRequest,
    ManualDecisionStats,
)
from .journal import SignalJournal
from .journal_models import JournalSignalList, JournalStats
from .live_engine import LiveMarketEngine
from .live_models import IntradayScan, LiveEngineStatus
from .live_store import LiveMarketStore
from .market_models import CandleSeries, MarketUniverse, SymbolPrice
from .market_analysis import analyze_market_snapshot
from .market_flow import build_market_flow_snapshot
from .models import PositionSizeRequest, PositionSizeResult, ScoreRequest, ScoreResult
from .ollama_analysis import OllamaMarketAnalyst
from .research_models import StrategyResearchStatus
from .scanner import MarketDataStaleError, MarketScanner
from .services import calculate_position_size, calculate_quality_score
from .flow_models import MarketFlowSnapshot


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    client = BybitPublicClient(
        base_url=settings.bybit_base_url,
        timeout_seconds=settings.bybit_request_timeout_seconds,
        max_retries=settings.bybit_max_retries,
        proxy=settings.bybit_http_proxy,
    )
    app.state.bybit_client = client
    app.state.default_universe_size = settings.market_universe_size
    app.state.market_scanner = MarketScanner(
        client=client,
        max_spread_bps=settings.market_max_spread_bps,
        min_turnover_24h_usdt=settings.market_min_turnover_24h_usdt,
        min_open_interest_usdt=settings.market_min_open_interest_usdt,
        min_listing_age_days=settings.market_min_listing_age_days,
        max_abs_funding_rate_pct=settings.market_max_abs_funding_rate_pct,
        max_abs_price_change_24h_pct=settings.market_max_abs_price_change_24h_pct,
        max_source_age_seconds=settings.market_max_source_age_seconds,
        allowed_base_coins=settings.market_allowed_base_coin_set(),
    )
    app.state.live_store = LiveMarketStore(max_candles=settings.intraday_candle_limit + 10)
    app.state.ollama_analyst = (
        OllamaMarketAnalyst(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            cache_seconds=settings.ollama_analysis_cache_seconds,
        )
        if settings.ollama_enabled
        else None
    )
    app.state.signal_journal = (
        SignalJournal(
            database_path=settings.journal_database_path,
            pending_expiry_hours=settings.journal_pending_expiry_hours,
            active_expiry_hours=settings.journal_active_expiry_hours,
            taker_fee_rate_pct=settings.journal_taker_fee_rate_pct,
            slippage_bps=settings.journal_slippage_bps,
            minimum_sample_size=settings.journal_minimum_sample_size,
        )
        if settings.journal_enabled
        else None
    )
    if app.state.signal_journal:
        await app.state.signal_journal.initialize()
    app.state.manual_journal = (
        ManualDecisionJournal(database_path=settings.manual_journal_database_path)
        if settings.manual_journal_enabled
        else None
    )
    if app.state.manual_journal:
        await app.state.manual_journal.initialize()
    app.state.auto_signal_journal = (
        AutoSignalJournal(database_path=settings.auto_signal_database_path)
        if settings.auto_signal_enabled
        else None
    )
    if app.state.auto_signal_journal:
        await app.state.auto_signal_journal.initialize()
    app.state.carry_test_journal = (
        CarryTestJournal(database_path=settings.carry_test_database_path)
        if settings.carry_test_enabled
        else None
    )
    if app.state.carry_test_journal:
        await app.state.carry_test_journal.initialize()
    app.state.live_engine = LiveMarketEngine(
        client=client,
        scanner=app.state.market_scanner,
        store=app.state.live_store,
        ws_url=settings.bybit_ws_url,
        universe_size=settings.market_universe_size,
        candle_limit=settings.intraday_candle_limit,
        universe_refresh_seconds=settings.intraday_universe_refresh_seconds,
        max_backfill_concurrency=settings.intraday_max_backfill_concurrency,
        max_message_age_seconds=settings.live_max_message_age_seconds,
        max_clock_skew_seconds=settings.live_max_clock_skew_seconds,
        max_candidate_spread_bps=settings.intraday_max_candidate_spread_bps,
        journal=app.state.signal_journal,
        journal_scan_seconds=settings.journal_scan_seconds,
        enabled=settings.live_market_data_enabled,
    )
    await app.state.live_engine.start()
    app.state.auto_signal_collector = (
        AutoSignalCollector(
            client=client,
            scanner=app.state.market_scanner,
            store=app.state.live_store,
            journal=app.state.auto_signal_journal,
            benchmark_symbol=settings.decision_benchmark_symbol,
            universe_size=settings.auto_signal_universe_size,
            scan_seconds=settings.auto_signal_scan_seconds,
            horizon_hours=settings.auto_signal_horizon_hours,
            startup_delay_seconds=settings.auto_signal_startup_delay_seconds,
        )
        if app.state.auto_signal_journal
        else None
    )
    if app.state.auto_signal_collector:
        await app.state.auto_signal_collector.start()
    app.state.carry_test_collector = (
        CarryTestCollector(
            client=client,
            journal=app.state.carry_test_journal,
            taker_fee_rate_pct=settings.journal_taker_fee_rate_pct,
            min_turnover_24h_usdt=settings.market_min_turnover_24h_usdt,
            min_open_interest_usdt=settings.market_min_open_interest_usdt,
            max_spread_bps=settings.market_max_spread_bps,
            allowed_base_coins=settings.market_allowed_base_coin_set(),
            top_n=settings.carry_test_top_n,
            scan_seconds=settings.carry_test_scan_seconds,
            horizon_hours=settings.carry_test_horizon_hours,
            startup_delay_seconds=settings.carry_test_startup_delay_seconds,
        )
        if app.state.carry_test_journal
        else None
    )
    if app.state.carry_test_collector:
        await app.state.carry_test_collector.start()
    try:
        yield
    finally:
        if app.state.carry_test_collector:
            await app.state.carry_test_collector.stop()
        if app.state.auto_signal_collector:
            await app.state.auto_signal_collector.stop()
        await app.state.live_engine.stop()
        if app.state.ollama_analyst:
            await app.state.ollama_analyst.close()
        await client.close()


app = FastAPI(
    title="Trade3 API",
    version="0.1.0",
    description="Advisory-only intraday futures analysis API. It cannot place orders.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "execution": "manual-only"}


@app.get("/v1/research/status", response_model=StrategyResearchStatus)
def research_status() -> StrategyResearchStatus:
    return StrategyResearchStatus(
        strategy="trend_continuation_v2",
        status="rejected",
        tested_start=datetime(2026, 4, 12, 23, 20, tzinfo=UTC),
        tested_end=datetime(2026, 5, 12, 23, 20, tzinfo=UTC),
        tested_symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        resolved_trades=65,
        net_expectancy_r=-0.3086,
        profit_factor=0.5773,
        approved_for_calls=False,
        note="Research only. Both V1 and the independently specified V2 were rejected.",
    )


@app.post("/v1/score", response_model=ScoreResult)
def score_setup(request: ScoreRequest) -> ScoreResult:
    return calculate_quality_score(request)


@app.post("/v1/risk/position-size", response_model=PositionSizeResult)
def position_size(request: PositionSizeRequest) -> PositionSizeResult:
    return calculate_position_size(request)


@app.get("/v1/markets/top", response_model=MarketUniverse)
async def top_markets(
    request: Request,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> MarketUniverse:
    try:
        effective_limit = limit or request.app.state.default_universe_size
        return await request.app.state.market_scanner.top_markets(effective_limit)
    except MarketDataStaleError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/markets/{symbol}/candles", response_model=CandleSeries)
async def market_candles(
    request: Request,
    symbol: Annotated[str, Path(pattern=r"^[A-Z0-9]{2,20}USDT$")],
    interval: Annotated[str, Query()] = "15",
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> CandleSeries:
    if interval not in SUPPORTED_INTERVALS_MINUTES:
        raise HTTPException(
            status_code=422,
            detail=f"interval must be one of {sorted(SUPPORTED_INTERVALS_MINUTES)}",
        )
    try:
        return await request.app.state.bybit_client.get_candles(symbol, interval, limit)
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/markets/{symbol}/price", response_model=SymbolPrice)
async def market_price(
    request: Request,
    symbol: Annotated[str, Path(pattern=r"^[A-Z0-9]{2,20}USDT$")],
) -> SymbolPrice:
    ticker = await request.app.state.live_store.ticker(symbol)
    if ticker and ticker.last_price:
        return SymbolPrice(symbol=symbol, price=ticker.last_price, source="live")
    try:
        series = await request.app.state.bybit_client.get_candles(symbol, "5", 1)
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not series.candles:
        raise HTTPException(status_code=503, detail="no price available")
    return SymbolPrice(symbol=symbol, price=series.candles[-1].close, source="rest")


@app.get("/v1/live/status", response_model=LiveEngineStatus)
async def live_status(request: Request) -> LiveEngineStatus:
    return await request.app.state.live_engine.status()


@app.get("/v1/intraday/candidates", response_model=IntradayScan)
async def intraday_candidates(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> IntradayScan:
    return await request.app.state.live_engine.scan(limit)


@app.get("/v1/funding/carry", response_model=CarryBoard)
async def funding_carry(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
    history: Annotated[bool, Query()] = True,
) -> CarryBoard:
    settings = get_settings()
    try:
        return await build_carry_board(
            request.app.state.bybit_client,
            limit=limit,
            taker_fee_rate_pct=settings.journal_taker_fee_rate_pct,
            min_turnover_24h_usdt=settings.market_min_turnover_24h_usdt,
            min_open_interest_usdt=settings.market_min_open_interest_usdt,
            max_spread_bps=settings.market_max_spread_bps,
            allowed_base_coins=settings.market_allowed_base_coin_set(),
            with_history=history,
        )
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/carry-test/stats", response_model=CarryTestStats)
async def carry_test_stats(request: Request) -> CarryTestStats:
    journal: CarryTestJournal | None = request.app.state.carry_test_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="carry forward test is disabled")
    settings = get_settings()
    return await journal.stats(
        horizon_hours=settings.carry_test_horizon_hours,
        scan_seconds=settings.carry_test_scan_seconds,
    )


@app.get("/v1/carry-test/positions", response_model=CarryPositionList)
async def carry_test_positions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CarryPositionList:
    journal: CarryTestJournal | None = request.app.state.carry_test_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="carry forward test is disabled")
    return CarryPositionList(positions=await journal.list_positions(limit))


@app.get("/v1/analysis/{symbol}", response_model=MarketAnalysisSnapshot)
async def market_analysis(
    request: Request,
    symbol: Annotated[str, Path(pattern=r"^[A-Z0-9]{2,20}USDT$")],
) -> MarketAnalysisSnapshot:
    return await _market_analysis_snapshot(request, symbol)


@app.get("/v1/analysis/{symbol}/ai", response_model=AiMarketReview)
async def ai_market_analysis(
    request: Request,
    symbol: Annotated[str, Path(pattern=r"^[A-Z0-9]{2,20}USDT$")],
) -> AiMarketReview:
    snapshot = await _market_analysis_snapshot(request, symbol)
    try:
        flow = await _market_flow_snapshot(request, symbol)
    except BybitApiError:
        flow = None
    analyst: OllamaMarketAnalyst | None = request.app.state.ollama_analyst
    if analyst is None:
        raise HTTPException(status_code=503, detail="Ollama analysis is disabled")
    return await analyst.review(snapshot, flow)


@app.get("/v1/flow/{symbol}", response_model=MarketFlowSnapshot)
async def market_flow(
    request: Request,
    symbol: Annotated[str, Path(pattern=r"^[A-Z0-9]{2,20}USDT$")],
) -> MarketFlowSnapshot:
    try:
        return await _market_flow_snapshot(request, symbol)
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _market_analysis_snapshot(
    request: Request,
    symbol: str,
) -> MarketAnalysisSnapshot:
    intervals = ("5", "15", "60", "240")

    async def candles(interval: str):
        cached = await request.app.state.live_store.candles(symbol, interval)
        if len(cached) >= 80:
            return cached
        series = await request.app.state.bybit_client.get_candles(symbol, interval, 300)
        return series.candles

    try:
        series = await asyncio.gather(*(candles(interval) for interval in intervals))
        ticker = await request.app.state.live_store.ticker(symbol)
        return analyze_market_snapshot(
            symbol=symbol,
            candles_by_interval=dict(zip(intervals, series, strict=True)),
            last_price=ticker.last_price if ticker else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BybitApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def _market_flow_snapshot(
    request: Request,
    symbol: str,
) -> MarketFlowSnapshot:
    return await build_market_flow_snapshot(
        symbol=symbol,
        client=request.app.state.bybit_client,
        store=request.app.state.live_store,
    )


@app.get("/v1/journal/signals", response_model=JournalSignalList)
async def journal_signals(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    state: Annotated[str | None, Query(pattern=r"^[a-z_]+$")] = None,
) -> JournalSignalList:
    journal = request.app.state.signal_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="signal journal is disabled")
    return JournalSignalList(signals=await journal.list_signals(limit, state))


@app.get("/v1/journal/stats", response_model=JournalStats)
async def journal_stats(request: Request) -> JournalStats:
    journal = request.app.state.signal_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="signal journal is disabled")
    return await journal.stats()


async def _benchmark_price(request: Request) -> float | None:
    symbol = get_settings().decision_benchmark_symbol
    ticker = await request.app.state.live_store.ticker(symbol)
    if ticker and ticker.last_price:
        return ticker.last_price
    try:
        series = await request.app.state.bybit_client.get_candles(symbol, "5", 1)
    except BybitApiError:
        return None
    return series.candles[-1].close if series.candles else None


@app.post("/v1/decisions", response_model=ManualDecision)
async def record_decision(request: Request, decision: ManualDecisionRequest) -> ManualDecision:
    journal: ManualDecisionJournal | None = request.app.state.manual_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="manual decision journal is disabled")
    return await journal.record(
        decision,
        datetime.now(UTC),
        benchmark_symbol=get_settings().decision_benchmark_symbol,
        benchmark_price=await _benchmark_price(request),
    )


@app.get("/v1/decisions", response_model=ManualDecisionList)
async def list_decisions(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    action: Annotated[str | None, Query(pattern=r"^[a-z]+$")] = None,
) -> ManualDecisionList:
    journal: ManualDecisionJournal | None = request.app.state.manual_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="manual decision journal is disabled")
    return ManualDecisionList(decisions=await journal.list_decisions(limit, action))


@app.get("/v1/decisions/stats", response_model=ManualDecisionStats)
async def decision_stats(request: Request) -> ManualDecisionStats:
    journal: ManualDecisionJournal | None = request.app.state.manual_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="manual decision journal is disabled")
    return await journal.stats(horizon_hours=get_settings().decision_horizon_hours)


@app.get("/v1/decisions.csv")
async def export_decisions_csv(request: Request) -> Response:
    journal: ManualDecisionJournal | None = request.app.state.manual_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="manual decision journal is disabled")
    decisions = await journal.list_decisions(limit=500)
    csv_text = decisions_to_csv(decisions)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trade3_decisions.csv"},
    )


@app.post("/v1/decisions/{decision_id}/outcome", response_model=ManualDecision)
async def resolve_decision(
    request: Request,
    decision_id: Annotated[int, Path(ge=1)],
    outcome: DecisionOutcomeRequest,
) -> ManualDecision:
    journal: ManualDecisionJournal | None = request.app.state.manual_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="manual decision journal is disabled")
    try:
        return await journal.resolve(
            decision_id,
            outcome,
            datetime.now(UTC),
            benchmark_price=await _benchmark_price(request),
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v1/auto-signals/stats", response_model=AutoSignalStats)
async def auto_signal_stats(request: Request) -> AutoSignalStats:
    journal: AutoSignalJournal | None = request.app.state.auto_signal_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="auto-signal forward test is disabled")
    settings = get_settings()
    return await journal.stats(
        horizon_hours=settings.auto_signal_horizon_hours,
        scan_seconds=settings.auto_signal_scan_seconds,
    )


@app.get("/v1/auto-signals", response_model=AutoSignalList)
async def list_auto_signals(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AutoSignalList:
    journal: AutoSignalJournal | None = request.app.state.auto_signal_journal
    if journal is None:
        raise HTTPException(status_code=503, detail="auto-signal forward test is disabled")
    return AutoSignalList(signals=await journal.list_signals(limit))
