# Shadow Test Protocol

The terminal can map structure, draw zones, and ask a local model. None of that
proves the human-plus-AI loop makes better-than-passive decisions. This protocol
answers one question with a result you can trust:

> Does recording discretionary calls with Trade3 beat doing nothing?

It is a falsification exercise. The default expectation is that it fails, and
that is an acceptable outcome. A clean "no edge" closes the trading thesis; a
clean "edge" earns the right to risk real money.

## Rules fixed before the test starts

Write these down and do not change them mid-run. Changing the rules after seeing
results is the in-sample tuning that killed V1 and V2.

- **Markets:** BTCUSDT and ETHUSDT only.
- **Horizon:** every decision is resolved with the price exactly 8 hours later.
  Pick one horizon and keep it for the whole run.
- **Sample size:** at least 40 resolved `accept` decisions before reading results.
  Stop-looking until then.
- **No trading:** zero real orders during the run. This measures decision
  quality, not execution.
- **One decision per setup:** do not record the same setup twice to pad the count.

## How to run it

1. Open the terminal. For each setup you would genuinely act on, press
   `ПРИНЯТЬ LONG/SHORT`, `ОТКЛОНИТЬ`, or `ОТЛОЖИТЬ`. The decision stores the
   price and the exact analysis and AI snapshot shown.
2. Eight hours later, read the price for that symbol and enter it in the decision
   journal (`Исход` column). The journal computes the directional return.
3. Repeat until you have 40+ resolved accepts.

## What counts as passing

The journal computes the buy-and-hold BTC benchmark automatically: it stores the
BTC price when you record a decision and again when you resolve it, then reports
`excess return vs BTC` per call plus the `beats BTC` rate across accepts. Compare
`accept` results against three passive benchmarks over the same windows:

- **Buy-and-hold** BTC (automatic: see the `vs BTC` column and the alpha stats).
- **DCA** (fixed buys at a regular interval), computed by hand for now.
- **A flat coin toss** at the same 8-hour horizon (50% directional baseline).

Pre-committed pass criteria, all required:

| Metric | Threshold |
| --- | --- |
| Accept win rate | > 50% and above the coin-toss baseline |
| Average accept return | positive after a 0.2% round-trip cost haircut |
| Result spread | not driven by one symbol or one lucky window |
| Beats buy-and-hold | higher return per unit of drawdown |

If any fails, stop. Convert the project to a learning and observability tool and
drop the money thesis. Do not re-test the same data to repair the result.

## Known limitations of this v1

- Returns are directional move only, before fees, slippage, and funding.
- The BTC benchmark is automatic, but its window is record-call time to
  resolve-call time. Resolve at the horizon so it lines up with your outcome
  price. The coin-toss significance (a z-score of the win rate) is in the stats;
  the DCA baseline is still computed by hand.
- An 8-hour horizon is one arbitrary choice. It tests the call, not a managed
  trade with a stop and target.

These limits are fine for a go/no-go signal. They are not fine for sizing real
risk. Passing this test earns a longer, stricter forward test, not live capital.

For the day-to-day routine, see [data-discipline.md](data-discipline.md).
