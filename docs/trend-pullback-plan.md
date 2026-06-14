# Trend Pullback Plan V1

## Boundary

The plan is deterministic and advisory. It does not predict returns or place
orders. A plan can only become `ready` after the scanner score reaches the
candidate threshold, a closed 5-minute candle confirms the trigger, structural
reward/risk is at least 1.5, and live price remains near the entry zone.

## Level Construction

1. Build an EMA20 pullback band of plus/minus 0.20 ATR on closed 5-minute data.
2. Search the last ten closed candles for a touch that preserves the EMA50 trend.
3. Set the trigger one exchange tick beyond the touch candle high for long plans
   or low for short plans.
4. Create a 0.10 ATR entry tolerance beyond the trigger.
5. Put invalidation beyond the pullback extreme with a 0.15 ATR buffer and
   enforce a minimum 0.75 ATR stop distance.
6. Find the nearest confirmed 15-minute pivot in the trade direction, falling
   back to the recent 60-candle extreme.
7. Block the plan when structural reward/risk is below 1.5 or invalidation is
   farther than 2.5 ATR.

Every price is rounded to `priceFilter.tickSize` from Bybit Instruments Info.

## States

- `waiting_pullback`: no recent EMA20 touch.
- `waiting_confirmation`: a touch exists but no closed trigger break exists.
- `waiting_entry`: confirmation exists but live price has not reached entry.
- `ready`: deterministic gates pass and live price is near the entry zone.
- `missed`: price moved more than 0.20 ATR beyond the entry tolerance.
- `watch`: geometry is valid but scanner score is below 70.
- `blocked`: structural R/R, stop distance, or invalidation failed.

## Limitations

- Pivot levels are mechanical and are not yet validated by historical outcomes.
- Fees, slippage, funding during the holding period, BTC correlation, news, and
  order-book depth are not included in plan geometry.
- `ready` means ready for manual review, not a recommendation to trade.
- Parameters must remain fixed during backtests to avoid look-ahead tuning.
