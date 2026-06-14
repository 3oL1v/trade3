# Decision and Risk Policy

## Quality Score

The initial score is a deterministic setup-quality ranking from 0 to 100. It is
not a probability of profit.

| Component | Weight |
| --- | ---: |
| 1h/4h direction alignment | 20% |
| 15m market structure | 15% |
| Volume and impulse | 15% |
| Level quality | 10% |
| 5m confirmation | 10% |
| Liquidity and spread | 10% |
| BTC and market regime | 10% |
| Reward-to-risk quality | 10% |

Explicit penalties cover adverse funding, nearby opposing levels, correlated
exposure, chasing an extended move, poor liquidity, and agent disagreement.

## Score Bands

- Below 60: reject
- 60-69: watch
- 70-79: standard candidate
- 80-100: strong candidate

Risk must not increase based on these bands until the score has been calibrated
on at least 200-300 timestamped, non-overlapping historical or forward signals.

## Initial Risk Limits

- Base risk per accepted trade: 0.25% of account equity.
- Maximum future risk after calibration: 0.50%.
- Maximum simultaneous portfolio risk: 1.00%.
- Daily loss limit: 1.00-1.50%.
- Isolated margin only.
- Leverage changes margin usage, not the maximum planned monetary loss.
- Position size is capped when the stop-based quantity would require more
  margin than the entered account equity. The UI must show the lower effective
  risk instead of presenting an impossible position.
