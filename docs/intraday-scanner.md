# Intraday Scanner V1

## Purpose

The scanner narrows an approved core set of Bybit USDT perpetuals to at most 20
liquid markets and then to a small list for human review. It does not predict
returns, place orders, or produce a calibrated probability.

## Data Flow

1. REST selects approved, mature, liquid markets and backfills candles.
2. Public WebSocket updates ticker and 5m/15m/1h candle state.
3. Only Bybit-confirmed closed candles enter indicator calculations.
4. Symbols with stale local receipt time or spread above 5 bps are rejected.
5. Remaining symbols receive a deterministic setup-quality score.

The broad universe also rejects contracts outside the configured core list,
contracts younger than 180 days, and markets whose absolute 24-hour move is
above 15% by default. Those limits reduce event-driven and newly listed
contracts; they do not make the remaining markets safe.

The engine reports degraded health when the host clock differs from Bybit by
more than five seconds. Time synchronization is an operational prerequisite for
intraday use.

## V1 Score

| Component | Maximum |
| --- | ---: |
| Clear 1h EMA20/EMA50 direction and slope | 30 |
| 15m structure aligned with 1h | 22 |
| 5m structure aligned with direction | 12 |
| Pullback proximity to 5m EMA20 | 15 |
| Closed 5m candle volume ratio | 8 |
| Live spread quality | 8 |
| Preferred 5m ATR regime | 5 |

Price extension beyond 1.5 ATR receives a progressive penalty and cannot become
a `candidate`. Extension beyond 2.5 ATR is omitted because it no longer
represents the trend-pullback setup.

## Result Bands

- `candidate`: score at least 70
- `watch`: score from 55 to 69.99
- `reject`: below 55 and omitted from the API result

The score must not control position size. It can only become a probability-like
measure after calibration on hundreds of timestamped, non-overlapping signals.

## Known Limitations

- EMA alignment is not a complete market-structure model.
- Volume is exchange-specific and can change rapidly.
- Correlation between altcoins and BTC is not yet included.
- Open interest change, liquidation data, and order-book imbalance are not yet
  part of the score.
- Trend-pullback candidates now receive a deterministic advisory plan; its
  parameters have not yet been validated by an outcome backtest.
