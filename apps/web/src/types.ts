export type EngineState = "disabled" | "starting" | "running" | "degraded" | "stopped";
export type Direction = "long" | "short";
export type Timeframe = "5" | "15" | "60" | "240";

export interface LiveEngineStatus {
  state: EngineState;
  enabled: boolean;
  journal_enabled: boolean;
  symbols: string[];
  intervals: string[];
  started_at: string | null;
  last_message_at: string | null;
  last_universe_refresh_at: string | null;
  reconnect_count: number;
  last_error: string | null;
  clock_skew_seconds: number | null;
  clock_synchronized: boolean;
  ticker_count: number;
  candle_series_count: number;
}

export interface TimeframeMetrics {
  interval: string;
  close: number;
  ema_20: number;
  ema_50: number;
  ema_20_slope_pct: number;
  atr_14: number;
  atr_percent: number;
  volume_ratio: number;
  closed_candles: number;
  last_closed_at: string;
}

export interface PriceZone {
  lower: number;
  upper: number;
}

export interface TradeTarget {
  label: string;
  price: number;
  reward_risk: number;
}

export interface TrendPullbackPlan {
  setup_type: "trend_pullback";
  status:
    | "waiting_pullback"
    | "waiting_confirmation"
    | "waiting_entry"
    | "ready"
    | "missed"
    | "blocked"
    | "watch";
  pullback_zone: PriceZone;
  trigger_price: number;
  entry_zone: PriceZone;
  invalidation_price: number;
  structural_target: number | null;
  risk_per_unit: number;
  structural_reward_risk: number | null;
  stop_distance_atr: number;
  touched_at: string | null;
  confirmation_at: string | null;
  targets: TradeTarget[];
  notes: string[];
}

export interface IntradayCandidate {
  rank: number;
  symbol: string;
  direction: Direction;
  score: number;
  state: "candidate" | "watch" | "reject";
  last_price: number;
  spread_bps: number;
  funding_rate_pct: number;
  turnover_24h_usdt: number;
  open_interest_usdt: number;
  pullback_distance_atr: number;
  timeframe_1h: TimeframeMetrics;
  timeframe_15m: TimeframeMetrics;
  timeframe_5m: TimeframeMetrics;
  reasons: string[];
  trade_plan: TrendPullbackPlan | null;
}

export interface IntradayScan {
  generated_at: string;
  engine_state: EngineState;
  universe_size: number;
  analyzed_count: number;
  candidates: IntradayCandidate[];
  score_note: string;
}

export interface Market {
  rank: number;
  symbol: string;
  base_coin: string;
  last_price: number;
  turnover_24h_usdt: number;
  open_interest_usdt: number;
  spread_bps: number;
  funding_rate_pct: number;
  price_change_24h_pct: number;
  launch_time: string;
  listing_age_days: number;
  tick_size: number;
}

export interface MarketUniverse {
  generated_at: string;
  source_time: string;
  requested_limit: number;
  eligible_count: number;
  rejected_count: number;
  markets: Market[];
}

export interface Candle {
  start_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover_usdt: number;
  is_closed: boolean;
}

export interface CandleSeries {
  symbol: string;
  interval: string;
  source_time: string;
  candles: Candle[];
}

export type MarketBias = "bullish" | "bearish" | "range" | "insufficient";
export type ZoneKind =
  | "support"
  | "resistance"
  | "bullish_fvg"
  | "bearish_fvg"
  | "bullish_order_block"
  | "bearish_order_block"
  | "liquidity_high"
  | "liquidity_low";

export interface SwingPoint {
  timeframe: string;
  kind: "high" | "low";
  time: string;
  price: number;
  strength: number;
}

export interface StructureEvent {
  timeframe: string;
  kind: string;
  time: string;
  price: number;
  description: string;
}

export interface TimeframeStructure {
  timeframe: string;
  bias: MarketBias;
  last_close: number;
  atr: number;
  swing_highs: SwingPoint[];
  swing_lows: SwingPoint[];
  events: StructureEvent[];
  summary: string;
}

export interface AnalysisZone {
  id: string;
  timeframe: string;
  kind: ZoneKind;
  lower: number;
  upper: number;
  start_time: string;
  end_time: string;
  status: string;
  strength: "low" | "medium" | "high";
  touches: number;
  rationale: string;
}

export interface AnalysisTrendLine {
  id: string;
  timeframe: string;
  kind: string;
  start_time: string;
  start_price: number;
  end_time: string;
  end_price: number;
}

export interface ScenarioTarget {
  label: string;
  price: number;
  reward_risk: number;
}

export interface TradeScenario {
  direction: Direction;
  status: "primary" | "alternative" | "watch";
  quality: "low" | "medium" | "high";
  entry_zone: PriceZone;
  trigger: string;
  invalidation_price: number;
  targets: ScenarioTarget[];
  evidence: string[];
  conflicts: string[];
}

export interface MarketAnalysisSnapshot {
  symbol: string;
  generated_at: string;
  last_price: number;
  preferred_direction: Direction | "neutral";
  decision: string;
  structures: TimeframeStructure[];
  zones: AnalysisZone[];
  trend_lines: AnalysisTrendLine[];
  scenarios: TradeScenario[];
  methodology_note: string;
}

export type AiVerdict = "long_candidate" | "short_candidate" | "wait";
export type AiConviction = "low" | "medium" | "high";

export interface AiMarketReview {
  symbol: string;
  status: "ready" | "unavailable";
  model: string;
  generated_at: string;
  snapshot_generated_at: string;
  runtime_ms: number;
  advisory_only: boolean;
  market_flow: MarketFlowSnapshot | null;
  observed_biases: {
    h4: MarketBias;
    h1: MarketBias;
    m15: MarketBias;
    m5: MarketBias;
  };
  verdict: AiVerdict;
  conviction: AiConviction;
  summary_code:
    | "aligned_long"
    | "aligned_short"
    | "mixed_context"
    | "range_context"
    | "trigger_pending"
    | "no_edge";
  supporting_fact_ids: string[];
  counter_fact_ids: string[];
  wait_condition_ids: string[];
  headline: string;
  thesis: string;
  confirmations: string[];
  counterarguments: string[];
  wait_for: string[];
  limitations: string[];
}

export interface OrderBookBand {
  distance_bps: number;
  bid_notional_usdt: number;
  ask_notional_usdt: number;
  imbalance: number;
  depth_complete: boolean;
}

export interface TradeFlowWindow {
  window_seconds: number;
  trade_count: number;
  taker_buy_usdt: number;
  taker_sell_usdt: number;
  imbalance: number;
  sample_truncated: boolean;
}

export interface LiquidationWindow {
  window_minutes: number;
  event_count: number;
  long_liquidated_usdt: number;
  short_liquidated_usdt: number;
  imbalance: number;
}

export interface MarketFlowSnapshot {
  symbol: string;
  generated_at: string;
  orderbook_source_time: string;
  mid_price: number;
  spread_bps: number;
  orderbook_bands: OrderBookBand[];
  trade_flow: TradeFlowWindow;
  liquidations: LiquidationWindow[];
  methodology_note: string;
}

export interface PositionSizeResult {
  requested_risk_usdt: number;
  risk_usdt: number;
  effective_risk_percent: number;
  stop_distance_percent: number;
  quantity: number;
  notional_usdt: number;
  estimated_margin_usdt: number;
  margin_utilization_percent: number;
  binding_constraint: "risk" | "margin";
}

export interface TargetHit {
  label: string;
  price: number;
  reward_risk: number;
  hit_at: string;
}

export interface JournalSignal {
  id: number;
  fingerprint: string;
  symbol: string;
  direction: Direction;
  setup_type: string;
  plan_status: string;
  lifecycle_state: string;
  outcome: string | null;
  score: number;
  signal_at: string;
  recorded_at: string;
  entered_at: string | null;
  closed_at: string | null;
  entry_lower: number;
  entry_upper: number;
  entry_price: number;
  stop_price: number;
  structural_reward_risk: number | null;
  targets: TradeTarget[];
  target_hits: TargetHit[];
  mfe_r: number;
  mae_r: number;
  result_r: number | null;
  execution_policy: string;
  taker_fee_rate_pct: number;
  slippage_bps: number;
  exit_reference_price: number | null;
  entry_fill_price: number | null;
  exit_fill_price: number | null;
  fee_cost_r: number | null;
  slippage_cost_r: number | null;
  net_result_r: number | null;
  last_evaluated_at: string | null;
}

export interface JournalStats {
  total_signals: number;
  pending_entry: number;
  active: number;
  closed: number;
  entered: number;
  ambiguous: number;
  expired_without_entry: number;
  missed_at_recording: number;
  stop_before_target: number;
  stop_after_target: number;
  tp1_hits: number;
  tp2_hits: number;
  structure_hits: number;
  tp1_hit_rate: number | null;
  average_mfe_r: number | null;
  average_mae_r: number | null;
  execution_policy: string;
  taker_fee_rate_pct: number;
  slippage_bps: number;
  resolved_trades: number;
  net_wins: number;
  net_losses: number;
  net_breakeven: number;
  net_win_rate: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  cumulative_net_r: number | null;
  max_drawdown_r: number | null;
  average_fee_cost_r: number | null;
  average_slippage_cost_r: number | null;
  minimum_sample_size: number;
  sample_sufficient: boolean;
  funding_included: boolean;
  note: string;
}

export interface StrategyResearchStatus {
  strategy: string;
  status: string;
  tested_start: string;
  tested_end: string;
  tested_symbols: string[];
  resolved_trades: number;
  net_expectancy_r: number;
  profit_factor: number;
  approved_for_calls: boolean;
  note: string;
}

export type DecisionAction = "accept" | "reject" | "defer";
export type DecisionDirection = "long" | "short" | "none";

export interface ManualDecisionRequest {
  symbol: string;
  action: DecisionAction;
  direction?: DecisionDirection;
  ai_verdict?: string | null;
  ai_conviction?: string | null;
  decision_price?: number | null;
  snapshot_generated_at?: string | null;
  note?: string | null;
  analysis_snapshot?: unknown;
  ai_review?: unknown;
}

export interface ManualDecision {
  id: number;
  symbol: string;
  action: DecisionAction;
  direction: DecisionDirection;
  ai_verdict: string | null;
  ai_conviction: string | null;
  agreed_with_ai: boolean | null;
  decision_price: number | null;
  snapshot_generated_at: string | null;
  recorded_at: string;
  note: string | null;
  outcome_price: number | null;
  outcome_at: string | null;
  outcome_return_pct: number | null;
  outcome_note: string | null;
  benchmark_symbol: string | null;
  benchmark_price: number | null;
  benchmark_outcome_price: number | null;
  benchmark_return_pct: number | null;
  excess_return_pct: number | null;
  analysis_snapshot: Record<string, unknown> | null;
  ai_review: Record<string, unknown> | null;
}

export interface ManualDecisionStats {
  total: number;
  accepted: number;
  rejected: number;
  deferred: number;
  longs: number;
  shorts: number;
  accept_rate: number | null;
  ai_comparable: number;
  agreed_with_ai: number;
  agreement_rate: number | null;
  resolved: number;
  accepts_resolved: number;
  accept_win_rate: number | null;
  average_accept_return_pct: number | null;
  benchmark_resolved: number;
  average_excess_return_pct: number | null;
  beat_benchmark_rate: number | null;
  note: string;
}
