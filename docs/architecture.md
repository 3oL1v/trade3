# Trade3 Architecture

## Objective

Trade3 supports a human intraday futures trader. It must improve consistency
and observability without pretending that an LLM can predict markets reliably.

## Decision Pipeline

1. Ingest public futures market data from Bybit V5.
2. Validate timestamps, missing candles, spread, and liquidity.
3. Rank up to 20 approved core markets by liquidity.
4. Build 4h/1h/15m/5m structure, zones, trend lines, and scenarios.
5. Add a Bybit flow snapshot: orderbook, taker trades, and liquidations.
6. Render candles and machine-generated annotations.
7. Ask local Ollama to select only validated facts and a conditional verdict.
8. Render the explanation from the exact snapshot used by the model.
9. Calculate position size deterministically when a scenario is selected.
10. Let the user make the final decision. Manual decision capture is a pending
    feature and must not reuse the rejected deterministic-strategy journal.

## Trust Boundaries

- Exchange data and TradingView alerts are untrusted external inputs.
- LLM output is advisory, schema-bound, and limited to known fact identifiers.
- Price levels come from numeric market data, never OCR alone.
- Position sizing is deterministic and cannot be overridden by an LLM.
- No component may place, cancel, or modify an exchange order.

## Initial Services

- `market-data`: REST/WebSocket ingestion and data-quality checks.
- `scanner`: top-20 universe and candidate ranking.
- `analysis`: structure, levels, setup detection, and score.
- `ollama-gateway`: structured local model calls.
- `orchestrator`: Ruflo agent roles and audit trail.
- `journal`: optional legacy strategy observations; disabled by default.
- `web`: chart, annotations, shortlist, and trade-plan card.

## Deployment

The first deployment is local-only on Windows. Ollama and the API bind to
loopback. External access, cloud deployment, and automated execution are out of
scope until separately reviewed.

## Bybit Universe Selection

The first scanner uses public REST endpoints and requires no API key. It keeps
only `Trading` USDT `LinearPerpetual` instruments whose base coin is in a
configurable core allowlist. It excludes pre-listing, stablecoin, and
commodity-linked base assets, validates bid/ask, and applies configurable
minimum turnover, open-interest, listing-age, funding, abnormal 24-hour move,
and maximum-spread thresholds. Eligible markets are ranked by 24-hour turnover;
this ranking measures current exchange liquidity, not expected return.

The allowlist is deliberately explicit rather than inferred from one turnover
snapshot. It must be reviewed periodically as market relevance changes. An
empty `TRADE3_MARKET_ALLOWED_BASE_COINS` disables the allowlist for research,
but that broader mode is not the default trading terminal configuration.

Ticker snapshots whose Bybit timestamp differs from local UTC beyond the
configured tolerance are rejected instead of being ranked. The REST universe
uses a 120-second tolerance because Bybit ticker snapshots may be CDN-delayed;
the future WebSocket signal path will use a separate, much stricter threshold.

## Live Intraday Engine

The engine backfills 5m, 15m, and 1h candles for the top-20 universe, then
subscribes to public ticker, kline, and `allLiquidation` topics. It sends a JSON
heartbeat every 20 seconds and reconnects with bounded exponential backoff.
Bybit ticker delta messages are merged with their preceding snapshots.

Indicators and rankings use only candles marked closed by Bybit (`confirm=true`).
The first ranking combines 1h trend, 15m alignment, 5m pullback distance,
closed-candle volume, spread, and volatility. It does not create an entry order
or claim a probability of profit. A stricter live spread limit is applied after
the broad universe filter, and stale per-symbol ticker updates are excluded
using local receipt time. Bybit's source timestamp is retained for audit but is
not used as the WebSocket liveness clock because host/server clock skew exists.
The measured skew is exposed in live status and marks the engine degraded when
it exceeds five seconds.

## Market Flow

The flow endpoint requests a depth-200 REST orderbook and up to 500 recent
public trades for the selected symbol. It calculates bid/ask imbalance inside
10 and 25 bps, marks incomplete depth coverage, and marks a trade sample when
the 500-trade cap truncates the requested 60-second window.

Liquidation events are collected from Bybit after local startup and summarized
over 5, 15, and 60 minutes. Their notional uses the reported bankruptcy price.
This is exchange-local flow, not an aggregated liquidation heatmap.

## Ollama Review

The local model receives deterministic structure, scenarios, and the flow
snapshot. It cannot return free-form facts or price coordinates. It selects a
verdict, qualitative clarity, fact IDs, and wait-condition IDs from enumerated
inputs. The API rejects changed timeframe biases, unknown identifiers, and
contradictory fact reuse. The response embeds the exact flow snapshot used so
the UI cannot explain one snapshot while displaying another.

## Signal Journal

The original live journal belongs to the rejected deterministic trend strategy
family and is disabled by default. Existing SQLite data is retained as research
history, but the analytical terminal must not present or record those rows as
current discretionary calls.

When explicitly enabled for legacy research, it deduplicates confirmation
candles, evaluates closed 5-minute candles, and applies its versioned virtual
execution baseline. It does not model funding or actual order-book impact.
A future manual journal needs a separate schema for user accept/reject/defer
decisions and the exact analysis snapshot shown at decision time.
