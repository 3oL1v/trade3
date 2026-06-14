# Trend Continuation V2 Trial 485: Rejected

## Decision

The frozen trial 485 configuration is rejected and must not be used for calls,
paper trading, position sizing, or further parameter tuning.

The overnight search produced positive train, validation, and first-holdout
results on five symbols. A later fixed verification preserved the exact
parameters and expanded the test to 20 symbols across three untouched periods:

- 2025-07-01 to 2025-09-01
- 2025-09-01 to 2025-11-01
- 2025-11-01 to 2026-01-01

## Fixed Verification Result

- Trades: 1,765
- Net expectancy: -0.1473R
- Profit factor: 0.7988
- Cumulative result: -259.9456R
- Maximum drawdown: 344.7419R
- Profitable symbols: 4 of 20
- Positive test windows: 0 of 3

Every predeclared acceptance check except minimum trade count failed.

## Interpretation

The positive five-symbol result did not generalize across time or market
breadth. The leading overnight variants were also nearly identical, so they
represented one parameter cluster rather than independent confirmations.

The July-December 2025 verification data is now observed. It must not be reused
as a holdout for future hypotheses or used to repair this strategy family.

Reports:

- `research/overnight/runs/20260612-000805/summary.json`
- `research/verification/runs/20260612-063728/summary.json`
