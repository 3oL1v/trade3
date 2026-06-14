# Legacy Strategy Signal Journal V2

> Disabled by default. Both deterministic strategy families were rejected, so
> this journal is retained only for historical research and must not be shown
> as a source of current discretionary calls.

## Purpose

The journal records confirmed deterministic plans and evaluates what market
prices did afterward. It measures the scanner; it does not claim that the user
entered a trade or earned the recorded result.

## Recording

A row is created only when:

- the setup has a closed 5-minute confirmation candle;
- plan state is `waiting_entry`, `ready`, or `missed`;
- the fingerprint of symbol, direction, setup, and confirmation candle is new.

The signal timestamp is the close of the confirmation candle, not its open.
Plan inputs and levels are immutable after insertion. A plan first observed as
`missed` is stored as `missed_at_recording` and is not treated as an entry.

## Evaluation

Only closed 5-minute candles are processed.

- Entry is detected when a candle overlaps the entry zone.
- Invalidation before entry closes the observation without a trade.
- MFE and MAE are measured in initial-risk units after entry.
- Target touches are timestamped individually.
- Stop before any target is recorded separately from stop after a target.
- Pending entries expire after six hours by default.
- Active observations expire after 24 hours by default.

If entry and stop, entry and target, or stop and a new target occur inside the
same candle, the result is `ambiguous`. OHLC cannot establish intrabar ordering,
so the journal does not guess.

## Statistics

The journal keeps the observational target/stop path and also evaluates one
fixed virtual execution policy:

- enter the entire position at the conservative edge of the entry zone;
- close the entire position on the first TP1 touch or stop touch;
- if neither is touched within the active lifetime, close at the latest closed
  5-minute candle;
- treat entry and exit as taker executions;
- apply fixed adverse slippage to both executions;
- exclude candles where OHLC cannot establish whether entry, stop, or target
  happened first.

The default non-VIP USDT perpetual taker fee is `0.055%` per execution. The
default slippage assumption is `2 bps` per execution. Both values are stored on
each signal, so later configuration changes do not rewrite old observations.

The API reports net win rate, expectancy in initial-risk units, profit factor,
cumulative net R, maximum drawdown, and average modeled costs. These values are
research statistics, not account P&L. Funding, latency, spread changes after
the signal, market impact, liquidation, and manual execution differences are
not included.

At least 100 resolved virtual trades are required before the UI stops flagging
the sample as insufficient. Reaching that threshold does not prove future
profitability and does not turn the deterministic score into a probability.

## Endpoints

```text
GET /v1/journal/signals?limit=100
GET /v1/journal/signals?state=active
GET /v1/journal/stats
```

SQLite data is local at `data/trade3_journal.sqlite3` by default and is excluded
from version control.

Fee reference:
[Bybit Futures Contracts: Fees Explained](https://www.bybit.com/en/help-center/article/Perpetual-Futures-Contract-Fees-Explained).
