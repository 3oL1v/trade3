# Data Discipline

The shadow test only produces a trustworthy answer if the data is collected honestly. The rules are fixed in `shadow-test.md`. This is the routine that keeps the dataset clean.

## Every session

- Record a decision only for setups you would genuinely act on. Press Accept (long or short), Reject, or Defer in the decision panel.
- Do not record the same setup twice to inflate the count.
- The decision stores the price and the exact analysis and AI snapshot shown, so you never have to reconstruct it later.

## At the horizon (8 hours later)

- The drawer flags decisions that are due with a "ПОРА" badge and a banner. Resolve them promptly so the outcome price matches the 8 hour mark.
- Click the live-price button or paste the price, then confirm. The journal computes the directional return and the excess versus buy-and-hold BTC.
- Resolve late and the benchmark window drifts; resolve at the horizon.

## Weekly review

- Export the journal to CSV from the drawer.
- Check the running stats: accept win rate, average return, alpha versus BTC, the coin-toss z-score, and the per-symbol breakdown.
- Do not change the rules based on what you see. Changing rules mid-run is the in-sample tuning that invalidates the test.

## Stop conditions

- Stop and read the result once you have at least 40 resolved accept decisions.
- Apply the pre-committed kill criterion in `shadow-test.md`. If it fails, close the trading branch. Do not re-test the same data to rescue it.

See [shadow-test.md](shadow-test.md) for the fixed rules and pass criteria.
