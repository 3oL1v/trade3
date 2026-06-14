import asyncio
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

from .bybit import _milliseconds_to_datetime
from .flow_models import LiquidationPrint
from .live_models import LiveTicker
from .market_models import Candle


class LiveMarketStore:
    def __init__(self, max_candles: int = 300) -> None:
        self._max_candles = max_candles
        self._lock = asyncio.Lock()
        self._ticker_fields: dict[str, dict[str, Any]] = {}
        self._tickers: dict[str, LiveTicker] = {}
        self._candles: dict[tuple[str, str], list[Candle]] = defaultdict(list)
        self._liquidations: dict[str, deque[LiquidationPrint]] = defaultdict(deque)
        self._last_message_at: datetime | None = None
        self._clock_skew_seconds: float | None = None

    async def seed_candles(self, symbol: str, interval: str, candles: list[Candle]) -> None:
        async with self._lock:
            self._candles[(symbol, interval)] = list(candles[-self._max_candles :])

    async def apply_message(self, message: dict[str, Any]) -> bool:
        topic = message.get("topic", "")
        source_time = _milliseconds_to_datetime(message.get("ts", 0))
        received_at = datetime.now(UTC)

        async with self._lock:
            if topic.startswith("tickers."):
                changed = self._apply_ticker(message, source_time, received_at)
            elif topic.startswith("kline."):
                changed = self._apply_kline(message)
            elif topic.startswith("allLiquidation."):
                changed = self._apply_liquidations(message, received_at)
            else:
                return False
            if changed:
                self._last_message_at = received_at
                self._clock_skew_seconds = (received_at - source_time).total_seconds()
            return changed

    def _apply_ticker(
        self,
        message: dict[str, Any],
        source_time: datetime,
        received_at: datetime,
    ) -> bool:
        data = message.get("data")
        if not isinstance(data, dict) or "symbol" not in data:
            return False
        symbol = data["symbol"]
        merged = self._ticker_fields.setdefault(symbol, {})
        merged.update(data)
        required = ("lastPrice", "bid1Price", "ask1Price")
        if any(not merged.get(field) for field in required):
            return False
        self._tickers[symbol] = LiveTicker(
            symbol=symbol,
            last_price=float(merged["lastPrice"]),
            mark_price=_float(merged.get("markPrice")),
            bid_price=float(merged["bid1Price"]),
            ask_price=float(merged["ask1Price"]),
            turnover_24h_usdt=_float(merged.get("turnover24h")),
            open_interest_usdt=_float(merged.get("openInterestValue")),
            funding_rate=_float(merged.get("fundingRate")),
            source_time=source_time,
            received_at=received_at,
        )
        return True

    def _apply_liquidations(
        self,
        message: dict[str, Any],
        received_at: datetime,
    ) -> bool:
        data = message.get("data")
        if not isinstance(data, list):
            return False
        changed = False
        newest_event_time: datetime | None = None
        for row in data:
            if not isinstance(row, dict):
                continue
            price = _float(row.get("p"))
            size = _float(row.get("v"))
            symbol = str(row.get("s", ""))
            side = str(row.get("S", ""))
            if not symbol or price <= 0 or size <= 0 or side not in {"Buy", "Sell"}:
                continue
            event = LiquidationPrint(
                symbol=symbol,
                position_side="long" if side == "Buy" else "short",
                price=price,
                size=size,
                notional_usdt=price * size,
                time=_milliseconds_to_datetime(row.get("T", message.get("ts", 0))),
            )
            self._liquidations[symbol].append(event)
            newest_event_time = (
                event.time if newest_event_time is None else max(newest_event_time, event.time)
            )
            changed = True
        cutoff = (newest_event_time or received_at) - timedelta(minutes=65)
        for events in self._liquidations.values():
            while events and events[0].time < cutoff:
                events.popleft()
        return changed

    def _apply_kline(self, message: dict[str, Any]) -> bool:
        topic_parts = message.get("topic", "").split(".")
        data = message.get("data")
        if len(topic_parts) != 3 or not isinstance(data, list) or not data:
            return False
        interval, symbol = topic_parts[1], topic_parts[2]
        row = data[0]
        candle = Candle(
            start_time=_milliseconds_to_datetime(row["start"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            turnover_usdt=float(row["turnover"]),
            is_closed=bool(row["confirm"]),
        )
        key = (symbol, interval)
        candles = self._candles[key]
        if candles and candles[-1].start_time == candle.start_time:
            candles[-1] = candle
        else:
            candles.append(candle)
            candles.sort(key=lambda item: item.start_time)
        self._candles[key] = candles[-self._max_candles :]
        return True

    async def ticker(self, symbol: str) -> LiveTicker | None:
        async with self._lock:
            return self._tickers.get(symbol)

    async def candles(self, symbol: str, interval: str) -> list[Candle]:
        async with self._lock:
            return list(self._candles.get((symbol, interval), []))

    async def liquidations(
        self,
        symbol: str,
        *,
        window_minutes: int,
        now: datetime | None = None,
    ) -> list[LiquidationPrint]:
        cutoff = (now or datetime.now(UTC)) - timedelta(minutes=window_minutes)
        async with self._lock:
            return [event for event in self._liquidations.get(symbol, ()) if event.time >= cutoff]

    async def counts(self) -> tuple[int, int]:
        async with self._lock:
            return len(self._tickers), len(self._candles)

    async def last_message_at(self) -> datetime | None:
        async with self._lock:
            return self._last_message_at

    async def clock_skew_seconds(self) -> float | None:
        async with self._lock:
            return self._clock_skew_seconds


def _float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)
