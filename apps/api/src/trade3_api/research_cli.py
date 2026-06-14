import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bybit import BybitPublicClient
from .config import get_settings
from .historical_replay import HistoricalReplay
from .historical_replay_v2 import V2HistoricalReplay


def main() -> None:
    asyncio.run(_run(_arguments()))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a closed-candle, price-only historical replay.",
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--strategy", choices=["v1", "v2"], default="v2")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument(
        "--end", help="Exclusive UTC ISO timestamp; defaults to current 5m boundary."
    )
    parser.add_argument("--spread-bps", type=float, default=1)
    parser.add_argument("--fee-pct", type=float, default=0.055)
    parser.add_argument("--slippage-bps", type=float, default=2)
    parser.add_argument("--warmup-days", type=int, default=4)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    if arguments.days < 1:
        raise SystemExit("--days must be at least 1")
    end = _end_time(arguments.end)
    start = end - timedelta(days=arguments.days)
    settings = get_settings()
    client = BybitPublicClient(
        settings.bybit_base_url,
        settings.bybit_request_timeout_seconds,
        settings.bybit_max_retries,
    )
    try:
        instruments = await client.get_usdt_perpetual_instruments()
        tick_sizes = {instrument.symbol: instrument.tick_size for instrument in instruments}
        replay_type = HistoricalReplay if arguments.strategy == "v1" else V2HistoricalReplay
        replay = replay_type(
            client,
            spread_bps=arguments.spread_bps,
            taker_fee_rate_pct=arguments.fee_pct,
            slippage_bps=arguments.slippage_bps,
            warmup_days=arguments.warmup_days,
        )
        report = await replay.run(arguments.symbols, tick_sizes, start, end)
    finally:
        await client.close()

    output = arguments.output or Path(
        f"research/results/replay-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    overall = report.overall
    print(f"report={output.resolve()}")
    print(
        f"signals={report.total_recorded_signals} resolved={report.resolved_trades} "
        f"ambiguous={report.ambiguous_signals} censored={report.censored_signals} "
        f"skipped={report.skipped_signals}"
    )
    print(
        f"win_rate={_format_percent(overall.win_rate)} "
        f"gross_expectancy={_format_r(report.gross_expectancy_r)} "
        f"expectancy={_format_r(overall.expectancy_r)} "
        f"average_cost={_format_r(report.average_total_cost_r)} "
        f"profit_factor={overall.profit_factor if overall.profit_factor is not None else 'n/a'} "
        f"max_drawdown={_format_r(overall.max_drawdown_r)}"
    )


def _end_time(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    now = datetime.now(UTC)
    return now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _format_r(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}R"


if __name__ == "__main__":
    main()
