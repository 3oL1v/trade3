import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

from .bybit import BybitPublicClient
from .historical_replay import INTERVAL_MINUTES
from .market_models import Candle


class HistoricalCandleCache:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    async def load_or_fetch(
        self,
        client: BybitPublicClient,
        symbols: list[str],
        start: datetime,
        end: datetime,
    ) -> dict[str, dict[str, list[Candle]]]:
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        dataset: dict[str, dict[str, list[Candle]]] = {}
        for symbol in symbols:
            dataset[symbol] = {}
            for interval in INTERVAL_MINUTES:
                path = self._path(symbol, interval, start, end)
                if path.exists():
                    candles = _read(path)
                else:
                    candles = await client.get_historical_candles(
                        symbol,
                        interval,
                        start,
                        end,
                    )
                    _write(path, candles)
                dataset[symbol][interval] = candles
        return dataset

    def _path(
        self,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> Path:
        start_key = start.strftime("%Y%m%dT%H%M")
        end_key = end.strftime("%Y%m%dT%H%M")
        return self._directory / f"{symbol}-{interval}-{start_key}-{end_key}.json.gz"


def slice_dataset(
    dataset: dict[str, dict[str, list[Candle]]],
    start: datetime,
    end: datetime,
) -> dict[str, dict[str, list[Candle]]]:
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    return {
        symbol: {
            interval: [candle for candle in candles if start <= candle.start_time < end]
            for interval, candles in by_interval.items()
        }
        for symbol, by_interval in dataset.items()
    }


def _write(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        [
            candle.start_time.isoformat(),
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            candle.turnover_usdt,
        ]
        for candle in candles
    ]
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        json.dump(rows, handle, separators=(",", ":"))
    temporary.replace(path)


def _read(path: Path) -> list[Candle]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = json.load(handle)
    return [
        Candle(
            start_time=datetime.fromisoformat(row[0]).astimezone(UTC),
            open=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            volume=row[5],
            turnover_usdt=row[6],
            is_closed=True,
        )
        for row in rows
    ]
