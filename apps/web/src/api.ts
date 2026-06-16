import type {
  AiMarketReview,
  CandleSeries,
  IntradayScan,
  JournalSignal,
  JournalStats,
  LiveEngineStatus,
  ManualDecision,
  ManualDecisionRequest,
  ManualDecisionStats,
  MarketAnalysisSnapshot,
  MarketFlowSnapshot,
  MarketUniverse,
  PositionSizeResult,
  StrategyResearchStatus,
  Timeframe,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  status: () => request<LiveEngineStatus>("/v1/live/status"),
  scan: () => request<IntradayScan>("/v1/intraday/candidates?limit=20"),
  universe: () => request<MarketUniverse>("/v1/markets/top?limit=20"),
  candles: (symbol: string, interval: Timeframe) =>
    request<CandleSeries>(`/v1/markets/${symbol}/candles?interval=${interval}&limit=240`),
  price: (symbol: string) =>
    request<{ symbol: string; price: number; source: string }>(
      `/v1/markets/${symbol}/price`,
    ),
  analysis: (symbol: string) =>
    request<MarketAnalysisSnapshot>(`/v1/analysis/${symbol}`),
  aiAnalysis: (symbol: string) =>
    request<AiMarketReview>(`/v1/analysis/${symbol}/ai`),
  flow: (symbol: string) => request<MarketFlowSnapshot>(`/v1/flow/${symbol}`),
  positionSize: (input: {
    equity_usdt: number;
    risk_percent: number;
    entry_price: number;
    stop_price: number;
    leverage: number;
  }) =>
    request<PositionSizeResult>("/v1/risk/position-size", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  journalSignals: (limit = 100) =>
    request<{ signals: JournalSignal[] }>(`/v1/journal/signals?limit=${limit}`),
  journalStats: () => request<JournalStats>("/v1/journal/stats"),
  researchStatus: () => request<StrategyResearchStatus>("/v1/research/status"),
  recordDecision: (input: ManualDecisionRequest) =>
    request<ManualDecision>("/v1/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  decisions: (limit = 100, action?: string) =>
    request<{ decisions: ManualDecision[] }>(
      `/v1/decisions?limit=${limit}${action ? `&action=${action}` : ""}`,
    ),
  decisionStats: () => request<ManualDecisionStats>("/v1/decisions/stats"),
  resolveDecision: (id: number, price: number, note?: string | null) =>
    request<ManualDecision>(`/v1/decisions/${id}/outcome`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ price, note: note ?? null }),
    }),
};
