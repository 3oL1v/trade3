# Historical Price-Only Replay

## Purpose

The replay tests the deterministic trend-pullback hypothesis before it is used
for discretionary futures calls. It shares the production indicator, plan,
journal, ambiguity, fee, and slippage code. It never places orders.

## Time Integrity

- Decisions are made only after a 5-minute candle closes.
- A 15-minute or 1-hour candle is visible only after its own close time.
- A signal is recorded only at the close immediately following its fresh
  confirmation candle.
- One unresolved virtual execution is allowed per symbol.
- Entry and outcome evaluation begin with the next 5-minute candle.
- Signals without enough future data remain censored and are not forced closed.

## Data Limitations

Bybit historical Kline data provides OHLCV and turnover, but not the complete
historical bid/ask, open-interest snapshot, funding state, or historical top-20
universe required to reproduce the live scanner exactly.

The replay therefore uses:

- a fixed symbol list, which creates survivorship bias;
- a fixed spread assumption for scoring;
- rolling 24-hour candle turnover;
- zero historical open interest and funding in the candidate snapshot;
- the same fixed taker fee and adverse slippage model as the signal journal.

This is a strategy-mechanics test, not a full exchange simulation.

## Running

From `apps/api`:

```powershell
uv run trade3-replay `
  --symbols BTCUSDT ETHUSDT SOLUSDT `
  --days 30 `
  --output C:\trade3\research\results\pilot.json
```

## First Fixed-Parameter Result

The first 30-day pilot covered `2026-05-12 23:20 UTC` through
`2026-06-11 23:20 UTC` on BTCUSDT, ETHUSDT, and SOLUSDT.

- Recorded signals: 35
- Resolved virtual trades: 13
- Ambiguous signals: 1
- Net win rate: 46.15%
- Gross expectancy: +0.0769R
- Average modeled costs: 0.5852R
- Net expectancy: -0.5083R
- Profit factor: 0.3212
- Maximum drawdown: 6.6079R

The sample is too small for parameter estimation, but it rejects using the
current V1 hypothesis for real calls. Its gross edge is negligible and is
overwhelmed by costs caused by tight stops. Score was not calibrated: the
90-100 bucket lost 1.1993R per trade in this sample.

Any V2 hypothesis must be specified before testing on a new, non-overlapping
date range. The V1 period must not be reused as proof for a tuned V2.

V2 was subsequently frozen and tested on the preceding non-overlapping
30-day holdout. It also failed, with `-0.3086R` net expectancy across 65
resolved trades. See [Trend Continuation V2](strategy-v2.md).
