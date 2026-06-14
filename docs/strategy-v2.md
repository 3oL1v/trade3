# Trend Continuation V2

## Frozen Hypothesis

V2 was specified after V1 failed and was tested without tuning on a separate
historical period.

- Regime: aligned 1-hour and 15-minute EMA20/EMA50 trend.
- Setup: a 15-minute pullback overlaps EMA20 while holding EMA50.
- Confirmation: a strong 15-minute close breaks the post-pullback range with
  volume at least 1.1 times its 20-bar average.
- Entry: opening price of the next 5-minute candle.
- Stop: beyond pullback structure, never tighter than 1.25 ATR or 0.75%.
- Filter: modeled round-trip fee and slippage must not exceed 0.20R.
- Target: entire position at 2R.
- Timeout: close after 12 hours if neither stop nor target is reached.
- Intrabar conflict: exclude as ambiguous.

These rules were frozen before the first V2 replay.

## Fixed Holdout Result

Test period: `2026-04-12 23:20 UTC` to `2026-05-12 23:20 UTC`.
Markets: BTCUSDT, ETHUSDT, SOLUSDT.

- Signals and resolved trades: 65
- Win rate: 32.31%
- Gross expectancy: -0.1448R
- Average modeled costs: 0.1638R
- Net expectancy: -0.3086R
- Profit factor: 0.5773
- Maximum drawdown: 23.2035R

V2 is rejected. The cost constraint worked, but the pattern itself had negative
gross expectancy. Increasing the score threshold based on this same result
would be in-sample tuning and is not accepted as validation.

Report:
`research/results/pilot-v2-btc-eth-sol-20260412-20260512.json`.
