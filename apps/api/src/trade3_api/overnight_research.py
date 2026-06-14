import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .bybit import BybitPublicClient
from .candle_cache import HistoricalCandleCache, slice_dataset
from .historical_replay_v2 import V2HistoricalReplay
from .ollama_research import OllamaResearchAgents
from .research_models import HistoricalReplayReport
from .strategy_v2 import DEFAULT_PARAMETERS, StrategyV2Parameters


class ResearchWindow(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_range(self) -> "ResearchWindow":
        if self.start >= self.end:
            raise ValueError("window start must be before end")
        return self


class OvernightResearchConfig(BaseModel):
    symbols: list[str] = Field(min_length=1)
    train: ResearchWindow
    validation: ResearchWindow
    holdout: ResearchWindow
    model: str = "qwen3.5:4b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    max_hours: float = Field(default=7, gt=0, le=24)
    max_trials: int = Field(default=60, ge=2, le=500)
    holdout_top: int = Field(default=5, ge=1, le=20)
    warmup_days: int = Field(default=7, ge=4, le=30)
    spread_bps: float = Field(default=1, ge=0)
    taker_fee_rate_pct: float = Field(default=0.055, ge=0)
    slippage_bps: float = Field(default=2, ge=0)
    random_seed: int = 20260612
    cache_directory: Path = Path("research/cache/bybit")
    output_directory: Path = Path("research/overnight/runs")

    @model_validator(mode="after")
    def validate_windows(self) -> "OvernightResearchConfig":
        if self.train.end > self.validation.start:
            raise ValueError("train and validation windows must not overlap")
        if self.validation.end > self.holdout.start:
            raise ValueError("validation and holdout windows must not overlap")
        return self


class ReplaySummary(BaseModel):
    trades: int = Field(ge=0)
    expectancy_r: float | None
    profit_factor: float | None
    cumulative_net_r: float | None
    max_drawdown_r: float | None
    win_rate: float | None
    profitable_symbols: int = Field(ge=0)


class TrialRecord(BaseModel):
    trial: int
    generated_at: datetime
    source: str
    parameters: StrategyV2Parameters
    proposer_note: str
    critic_note: str
    train: ReplaySummary
    validation: ReplaySummary
    research_score: float


class HoldoutRecord(BaseModel):
    rank_before_holdout: int
    trial: int
    parameters: StrategyV2Parameters
    train: ReplaySummary
    validation: ReplaySummary
    holdout: ReplaySummary
    holdout_report: str


class OvernightResearchRunner:
    def __init__(
        self,
        config: OvernightResearchConfig,
        *,
        project_root: Path,
    ) -> None:
        self._config = config
        self._root = project_root
        self._rng = random.Random(config.random_seed)
        self._records: list[TrialRecord] = []

    async def run(self) -> Path:
        started_at = datetime.now(UTC)
        run_directory = (
            self._root / self._config.output_directory / started_at.strftime("%Y%m%d-%H%M%S")
        )
        run_directory.mkdir(parents=True, exist_ok=False)
        latest = self._root / "research/overnight/latest-run.txt"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(str(run_directory.resolve()), encoding="utf-8")
        _write_json(run_directory / "config.json", self._config.model_dump(mode="json"))
        self._write_state(run_directory, "loading_market_data", started_at)

        client = BybitPublicClient(
            "https://api.bybit.com",
            max_retries=8,
            minimum_request_interval_seconds=0.35,
        )
        agents = OllamaResearchAgents(
            base_url=self._config.ollama_base_url,
            model=self._config.model,
        )
        try:
            instruments = await client.get_usdt_perpetual_instruments()
            tick_sizes = {instrument.symbol: instrument.tick_size for instrument in instruments}
            symbols = [symbol.upper() for symbol in self._config.symbols]
            missing = [symbol for symbol in symbols if symbol not in tick_sizes]
            if missing:
                raise ValueError(f"Bybit instruments unavailable: {', '.join(missing)}")

            cache_start = min(
                self._config.train.start,
                self._config.validation.start,
                self._config.holdout.start,
            ) - timedelta(days=self._config.warmup_days)
            cache_end = max(
                self._config.train.end,
                self._config.validation.end,
                self._config.holdout.end,
            )
            cache = HistoricalCandleCache(self._root / self._config.cache_directory)
            dataset = await cache.load_or_fetch(
                client,
                symbols,
                cache_start,
                cache_end,
            )
            split_data = {
                "train": slice_dataset(
                    dataset,
                    self._config.train.start - timedelta(days=self._config.warmup_days),
                    self._config.train.end,
                ),
                "validation": slice_dataset(
                    dataset,
                    self._config.validation.start - timedelta(days=self._config.warmup_days),
                    self._config.validation.end,
                ),
                "holdout": slice_dataset(
                    dataset,
                    self._config.holdout.start - timedelta(days=self._config.warmup_days),
                    self._config.holdout.end,
                ),
            }
            self._write_state(run_directory, "searching", started_at)
            await self._search(
                run_directory,
                started_at,
                client,
                agents,
                symbols,
                tick_sizes,
                split_data,
            )
            self._write_state(run_directory, "evaluating_holdout", started_at)
            holdout = self._evaluate_holdout(
                run_directory,
                client,
                symbols,
                tick_sizes,
                split_data["holdout"],
            )
            _write_json(
                run_directory / "summary.json",
                {
                    "status": "completed",
                    "started_at": started_at,
                    "completed_at": datetime.now(UTC),
                    "trials_completed": len(self._records),
                    "positive_validation_trials": sum(
                        (record.validation.expectancy_r or 0) > 0 for record in self._records
                    ),
                    "holdout": [record.model_dump(mode="json") for record in holdout],
                    "warning": (
                        "Research output only. Positive historical results are not permission "
                        "to trade or increase risk."
                    ),
                },
            )
            self._write_state(run_directory, "completed", started_at)
            print(f"completed run={run_directory.resolve()}", flush=True)
            return run_directory
        except Exception as exc:
            self._write_state(run_directory, "failed", started_at, error=str(exc))
            raise
        finally:
            await agents.close()
            await client.close()

    async def _search(
        self,
        run_directory: Path,
        started_at: datetime,
        client: BybitPublicClient,
        agents: OllamaResearchAgents,
        symbols: list[str],
        tick_sizes: dict[str, float],
        split_data: dict[str, dict[str, dict[str, list[Any]]]],
    ) -> None:
        deadline = monotonic() + self._config.max_hours * 3600
        seen: set[str] = set()
        for trial_number in range(1, self._config.max_trials + 1):
            if trial_number > 1 and monotonic() >= deadline:
                break
            source = "baseline"
            proposer_note = "Current V2 defaults."
            critic_note = "Baseline is always measured before generated variants."
            parameters = DEFAULT_PARAMETERS
            if trial_number > 1:
                parameters, source, proposer_note, critic_note = await self._next_parameters(
                    agents,
                    trial_number,
                    seen,
                )
            key = _parameter_key(parameters)
            if key in seen:
                parameters = _random_parameters(self._rng)
                key = _parameter_key(parameters)
                source = "random_deduplication_fallback"
                critic_note = "Generated parameters duplicated a prior trial."
            seen.add(key)

            train_report = self._replay(
                client,
                symbols,
                tick_sizes,
                self._config.train,
                split_data["train"],
                parameters,
            )
            validation_report = self._replay(
                client,
                symbols,
                tick_sizes,
                self._config.validation,
                split_data["validation"],
                parameters,
            )
            record = TrialRecord(
                trial=trial_number,
                generated_at=datetime.now(UTC),
                source=source,
                parameters=parameters,
                proposer_note=proposer_note,
                critic_note=critic_note,
                train=_summarize(train_report),
                validation=_summarize(validation_report),
                research_score=_research_score(train_report, validation_report),
            )
            self._records.append(record)
            _append_json_line(run_directory / "trials.jsonl", record.model_dump(mode="json"))
            self._write_leaderboard(run_directory)
            self._write_state(run_directory, "searching", started_at)
            print(
                f"trial={trial_number} source={source} score={record.research_score:.3f} "
                f"train={record.train.expectancy_r} validation={record.validation.expectancy_r}",
                flush=True,
            )

    async def _next_parameters(
        self,
        agents: OllamaResearchAgents,
        trial_number: int,
        seen: set[str],
    ) -> tuple[StrategyV2Parameters, str, str, str]:
        history = _agent_history(self._records)
        try:
            proposal = await agents.propose(
                trial_number=trial_number,
                history=history,
            )
            critique = await agents.critique(
                proposal=proposal,
                history=history,
            )
            parameters = proposal.parameters if critique.accepted else critique.parameters
            if _parameter_key(parameters) in seen:
                parameters = _jitter(parameters, self._rng)
            return (
                parameters,
                "ollama_proposer_critic",
                proposal.rationale,
                critique.critique,
            )
        except Exception as exc:
            return (
                _random_parameters(self._rng),
                "random_agent_error_fallback",
                "Ollama proposal unavailable.",
                f"{type(exc).__name__}: {exc}"[:500],
            )

    def _replay(
        self,
        client: BybitPublicClient,
        symbols: list[str],
        tick_sizes: dict[str, float],
        window: ResearchWindow,
        dataset: dict[str, dict[str, list[Any]]],
        parameters: StrategyV2Parameters,
    ) -> HistoricalReplayReport:
        replay = V2HistoricalReplay(
            client,
            spread_bps=self._config.spread_bps,
            taker_fee_rate_pct=self._config.taker_fee_rate_pct,
            slippage_bps=self._config.slippage_bps,
            warmup_days=self._config.warmup_days,
            parameters=parameters,
        )
        return replay.run_cached(
            symbols,
            tick_sizes,
            window.start,
            window.end,
            dataset,
        )

    def _evaluate_holdout(
        self,
        run_directory: Path,
        client: BybitPublicClient,
        symbols: list[str],
        tick_sizes: dict[str, float],
        dataset: dict[str, dict[str, list[Any]]],
    ) -> list[HoldoutRecord]:
        leading = sorted(
            self._records,
            key=lambda record: record.research_score,
            reverse=True,
        )[: self._config.holdout_top]
        results: list[HoldoutRecord] = []
        for rank, record in enumerate(leading, start=1):
            report = self._replay(
                client,
                symbols,
                tick_sizes,
                self._config.holdout,
                dataset,
                record.parameters,
            )
            report_path = run_directory / f"holdout-trial-{record.trial}.json"
            report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            results.append(
                HoldoutRecord(
                    rank_before_holdout=rank,
                    trial=record.trial,
                    parameters=record.parameters,
                    train=record.train,
                    validation=record.validation,
                    holdout=_summarize(report),
                    holdout_report=str(report_path.resolve()),
                )
            )
        return results

    def _write_leaderboard(self, run_directory: Path) -> None:
        leading = sorted(
            self._records,
            key=lambda record: record.research_score,
            reverse=True,
        )[:20]
        _write_json(
            run_directory / "leaderboard.json",
            [record.model_dump(mode="json") for record in leading],
        )

    def _write_state(
        self,
        run_directory: Path,
        status: str,
        started_at: datetime,
        *,
        error: str | None = None,
    ) -> None:
        state = {
            "status": status,
            "started_at": started_at,
            "updated_at": datetime.now(UTC),
            "trials_completed": len(self._records),
            "best_score": max(
                (record.research_score for record in self._records),
                default=None,
            ),
            "error": error,
        }
        _write_json(run_directory / "state.json", state)


def _summarize(report: HistoricalReplayReport) -> ReplaySummary:
    by_symbol: dict[str, list[float]] = {}
    for trade in report.trades:
        by_symbol.setdefault(trade.symbol, []).append(trade.net_result_r)
    profitable_symbols = sum(sum(results) > 0 for results in by_symbol.values())
    return ReplaySummary(
        trades=report.overall.trades,
        expectancy_r=report.overall.expectancy_r,
        profit_factor=report.overall.profit_factor,
        cumulative_net_r=report.overall.cumulative_net_r,
        max_drawdown_r=report.overall.max_drawdown_r,
        win_rate=report.overall.win_rate,
        profitable_symbols=profitable_symbols,
    )


def _research_score(
    train: HistoricalReplayReport,
    validation: HistoricalReplayReport,
) -> float:
    train_exp = train.overall.expectancy_r if train.overall.expectancy_r is not None else -2
    validation_exp = (
        validation.overall.expectancy_r if validation.overall.expectancy_r is not None else -2
    )
    train_pf = min(train.overall.profit_factor or 0, 3)
    validation_pf = min(validation.overall.profit_factor or 0, 3)
    drawdown = (train.overall.max_drawdown_r or 50) + (validation.overall.max_drawdown_r or 50)
    minimum_trades = min(train.overall.trades, validation.overall.trades)
    trade_penalty = max(0, 20 - minimum_trades) * 1.5
    instability = abs(train_exp - validation_exp) * 20
    score = (
        min(train_exp, validation_exp) * 60
        + (train_exp + validation_exp) * 20
        + (train_pf + validation_pf) * 3
        - drawdown * 0.25
        - trade_penalty
        - instability
    )
    return round(score, 4)


def _agent_history(records: list[TrialRecord]) -> list[dict[str, Any]]:
    leading = sorted(records, key=lambda record: record.research_score, reverse=True)[:6]
    recent = records[-4:]
    unique = {record.trial: record for record in [*leading, *recent]}
    return [
        {
            "trial": record.trial,
            "score": record.research_score,
            "parameters": record.parameters.model_dump(),
            "train": record.train.model_dump(),
            "validation": record.validation.model_dump(),
        }
        for record in unique.values()
    ]


def _random_parameters(rng: random.Random) -> StrategyV2Parameters:
    min_stop_percent = rng.choice([0.35, 0.5, 0.65, 0.75, 0.9, 1.1])
    max_stop_percent = rng.choice([2.0, 2.5, 3.0, 3.5, 4.0])
    return StrategyV2Parameters(
        min_trend_separation_atr=rng.choice([0.2, 0.3, 0.4, 0.55, 0.7, 0.9]),
        pullback_lookback=rng.randint(2, 8),
        pullback_band_atr=rng.choice([0.1, 0.15, 0.25, 0.35, 0.5]),
        min_stop_atr=rng.choice([0.75, 1.0, 1.25, 1.5, 1.75, 2.0]),
        min_stop_percent=min_stop_percent,
        max_stop_percent=max(max_stop_percent, min_stop_percent + 0.5),
        target_r=rng.choice([1.5, 1.8, 2.0, 2.25, 2.5, 3.0]),
        min_volume_ratio=rng.choice([0.75, 0.9, 1.0, 1.1, 1.25, 1.5]),
        min_close_strength=rng.choice([0.55, 0.6, 0.65, 0.7, 0.75]),
        stop_buffer_atr=rng.choice([0.1, 0.15, 0.25, 0.35, 0.45]),
        max_modeled_cost_r=rng.choice([0.15, 0.2, 0.25, 0.3]),
        max_hold_hours=rng.choice([6, 8, 12, 16, 24]),
    )


def _jitter(
    parameters: StrategyV2Parameters,
    rng: random.Random,
) -> StrategyV2Parameters:
    field = rng.choice(
        [
            "min_trend_separation_atr",
            "pullback_lookback",
            "pullback_band_atr",
            "target_r",
            "min_volume_ratio",
            "min_close_strength",
            "max_hold_hours",
        ]
    )
    replacement = _random_parameters(rng)
    return parameters.model_copy(update={field: getattr(replacement, field)})


def _parameter_key(parameters: StrategyV2Parameters) -> str:
    return json.dumps(parameters.model_dump(), sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _append_json_line(path: Path, payload: Any) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str))
        handle.write("\n")
