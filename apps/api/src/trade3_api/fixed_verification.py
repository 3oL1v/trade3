import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .bybit import BybitPublicClient
from .candle_cache import HistoricalCandleCache, slice_dataset
from .historical_replay_v2 import V2HistoricalReplay
from .overnight_research import ReplaySummary, ResearchWindow, _summarize
from .research_models import HistoricalReplayReport, ReplayTrade
from .strategy_v2 import StrategyV2Parameters


class VerificationCriteria(BaseModel):
    minimum_total_trades: int = Field(default=200, ge=1)
    minimum_profitable_symbols: int = Field(default=12, ge=1)
    minimum_aggregate_profit_factor: float = Field(default=1.15, gt=1)
    require_positive_expectancy_each_window: bool = True
    maximum_single_symbol_profit_share: float = Field(default=0.35, gt=0, le=1)


class FixedVerificationConfig(BaseModel):
    hypothesis_id: str
    source: str
    symbols: list[str] = Field(min_length=2)
    windows: list[ResearchWindow] = Field(min_length=2)
    parameters: StrategyV2Parameters
    criteria: VerificationCriteria = VerificationCriteria()
    warmup_days: int = Field(default=7, ge=4, le=30)
    spread_bps: float = Field(default=1, ge=0)
    taker_fee_rate_pct: float = Field(default=0.055, ge=0)
    slippage_bps: float = Field(default=2, ge=0)
    cache_directory: Path = Path("research/cache/bybit-fixed-verification")
    output_directory: Path = Path("research/verification/runs")


class SymbolSummary(BaseModel):
    symbol: str
    trades: int = Field(ge=0)
    expectancy_r: float | None
    cumulative_net_r: float | None
    profit_factor: float | None
    win_rate: float | None


class VerificationDecision(BaseModel):
    passed: bool
    checks: dict[str, bool]
    total_trades: int
    aggregate_expectancy_r: float | None
    aggregate_profit_factor: float | None
    cumulative_net_r: float | None
    max_drawdown_r: float | None
    profitable_symbols: int
    largest_positive_symbol_share: float | None


class FixedVerificationRunner:
    def __init__(
        self,
        config: FixedVerificationConfig,
        *,
        project_root: Path,
    ) -> None:
        self._config = config
        self._root = project_root

    async def run(self) -> Path:
        started_at = datetime.now(UTC)
        run_directory = (
            self._root / self._config.output_directory / started_at.strftime("%Y%m%d-%H%M%S")
        )
        run_directory.mkdir(parents=True, exist_ok=False)
        latest = self._root / "research/verification/latest-run.txt"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(str(run_directory.resolve()), encoding="utf-8")
        _write_json(run_directory / "config.json", self._config.model_dump(mode="json"))
        self._write_state(run_directory, "loading_market_data", started_at)

        client = BybitPublicClient(
            "https://api.bybit.com",
            max_retries=8,
            minimum_request_interval_seconds=0.35,
        )
        try:
            symbols = [symbol.upper() for symbol in self._config.symbols]
            instruments = await client.get_usdt_perpetual_instruments()
            tick_sizes = {instrument.symbol: instrument.tick_size for instrument in instruments}
            missing = [symbol for symbol in symbols if symbol not in tick_sizes]
            if missing:
                raise ValueError(f"Bybit instruments unavailable: {', '.join(missing)}")

            cache_start = min(window.start for window in self._config.windows) - timedelta(
                days=self._config.warmup_days
            )
            cache_end = max(window.end for window in self._config.windows)
            cache = HistoricalCandleCache(self._root / self._config.cache_directory)
            dataset = await cache.load_or_fetch(
                client,
                symbols,
                cache_start,
                cache_end,
            )

            self._write_state(run_directory, "replaying", started_at)
            reports = []
            for index, window in enumerate(self._config.windows, start=1):
                report = self._replay(
                    client,
                    symbols,
                    tick_sizes,
                    window,
                    slice_dataset(
                        dataset,
                        window.start - timedelta(days=self._config.warmup_days),
                        window.end,
                    ),
                )
                report_path = run_directory / f"window-{index}.json"
                report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
                reports.append(report)
                print(
                    f"window={index} trades={report.overall.trades} "
                    f"expectancy={report.overall.expectancy_r} "
                    f"profit_factor={report.overall.profit_factor}",
                    flush=True,
                )

            trades = sorted(
                [trade for report in reports for trade in report.trades],
                key=lambda trade: (trade.signal_at, trade.symbol),
            )
            symbol_summaries = _symbol_summaries(symbols, trades)
            decision = evaluate_verification(
                self._config.criteria,
                [_summarize(report) for report in reports],
                symbol_summaries,
                trades,
            )
            _write_json(
                run_directory / "summary.json",
                {
                    "status": "completed",
                    "hypothesis_id": self._config.hypothesis_id,
                    "source": self._config.source,
                    "started_at": started_at,
                    "completed_at": datetime.now(UTC),
                    "parameters": self._config.parameters.model_dump(),
                    "windows": [
                        {
                            "window": window.model_dump(mode="json"),
                            "metrics": _summarize(report).model_dump(mode="json"),
                            "report": str((run_directory / f"window-{index}.json").resolve()),
                        }
                        for index, (window, report) in enumerate(
                            zip(self._config.windows, reports, strict=True),
                            start=1,
                        )
                    ],
                    "symbols": [summary.model_dump(mode="json") for summary in symbol_summaries],
                    "decision": decision.model_dump(mode="json"),
                    "warning": (
                        "This is a frozen historical verification, not permission to trade. "
                        "No parameters were changed after reading these windows."
                    ),
                },
            )
            self._write_state(
                run_directory,
                "completed",
                started_at,
                decision=decision.passed,
            )
            print(
                f"completed run={run_directory.resolve()} passed={decision.passed}",
                flush=True,
            )
            return run_directory
        except Exception as exc:
            self._write_state(run_directory, "failed", started_at, error=str(exc))
            raise
        finally:
            await client.close()

    def _replay(
        self,
        client: BybitPublicClient,
        symbols: list[str],
        tick_sizes: dict[str, float],
        window: ResearchWindow,
        dataset: dict[str, dict[str, list[Any]]],
    ) -> HistoricalReplayReport:
        replay = V2HistoricalReplay(
            client,
            spread_bps=self._config.spread_bps,
            taker_fee_rate_pct=self._config.taker_fee_rate_pct,
            slippage_bps=self._config.slippage_bps,
            warmup_days=self._config.warmup_days,
            parameters=self._config.parameters,
        )
        return replay.run_cached(
            symbols,
            tick_sizes,
            window.start,
            window.end,
            dataset,
        )

    def _write_state(
        self,
        run_directory: Path,
        status: str,
        started_at: datetime,
        *,
        error: str | None = None,
        decision: bool | None = None,
    ) -> None:
        _write_json(
            run_directory / "state.json",
            {
                "status": status,
                "started_at": started_at,
                "updated_at": datetime.now(UTC),
                "passed": decision,
                "error": error,
            },
        )


def evaluate_verification(
    criteria: VerificationCriteria,
    windows: list[ReplaySummary],
    symbols: list[SymbolSummary],
    trades: list[ReplayTrade],
) -> VerificationDecision:
    results = [trade.net_result_r for trade in trades]
    wins = [result for result in results if result > 0]
    losses = [result for result in results if result < 0]
    total_net = sum(results)
    profitable = [summary for summary in symbols if (summary.cumulative_net_r or 0) > 0]
    positive_symbol_profits = [summary.cumulative_net_r or 0 for summary in profitable]
    largest_share = (
        max(positive_symbol_profits) / sum(positive_symbol_profits)
        if positive_symbol_profits and sum(positive_symbol_profits) > 0
        else None
    )
    aggregate_pf = sum(wins) / abs(sum(losses)) if wins and losses else None
    expectancy = total_net / len(results) if results else None
    checks = {
        "minimum_total_trades": len(results) >= criteria.minimum_total_trades,
        "minimum_profitable_symbols": (len(profitable) >= criteria.minimum_profitable_symbols),
        "minimum_aggregate_profit_factor": (
            aggregate_pf is not None and aggregate_pf >= criteria.minimum_aggregate_profit_factor
        ),
        "positive_expectancy_each_window": (
            not criteria.require_positive_expectancy_each_window
            or all((window.expectancy_r or 0) > 0 for window in windows)
        ),
        "maximum_single_symbol_profit_share": (
            largest_share is not None
            and largest_share <= criteria.maximum_single_symbol_profit_share
        ),
    }
    return VerificationDecision(
        passed=all(checks.values()),
        checks=checks,
        total_trades=len(results),
        aggregate_expectancy_r=round(expectancy, 4) if expectancy is not None else None,
        aggregate_profit_factor=round(aggregate_pf, 4) if aggregate_pf is not None else None,
        cumulative_net_r=round(total_net, 4) if results else None,
        max_drawdown_r=_max_drawdown(results),
        profitable_symbols=len(profitable),
        largest_positive_symbol_share=(
            round(largest_share, 4) if largest_share is not None else None
        ),
    )


def _symbol_summaries(
    symbols: list[str],
    trades: list[ReplayTrade],
) -> list[SymbolSummary]:
    summaries = []
    for symbol in symbols:
        results = [trade.net_result_r for trade in trades if trade.symbol == symbol]
        wins = [result for result in results if result > 0]
        losses = [result for result in results if result < 0]
        summaries.append(
            SymbolSummary(
                symbol=symbol,
                trades=len(results),
                expectancy_r=round(sum(results) / len(results), 4) if results else None,
                cumulative_net_r=round(sum(results), 4) if results else None,
                profit_factor=(round(sum(wins) / abs(sum(losses)), 4) if wins and losses else None),
                win_rate=round(len(wins) / len(results), 4) if results else None,
            )
        )
    return summaries


def _max_drawdown(results: list[float]) -> float | None:
    if not results:
        return None
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for result in results:
        equity += result
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return round(maximum, 4)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)
