import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { Analysis, BottomDesk } from "./DecisionDesk";
import type { Market, MarketAnalysisSnapshot } from "./types";

vi.mock("./api", () => ({
  api: {
    positionSize: vi.fn(),
  },
}));

const analysis: MarketAnalysisSnapshot = {
  symbol: "BTCUSDT",
  generated_at: "2026-06-12T10:00:00Z",
  last_price: 100,
  preferred_direction: "long",
  decision: "Long context is preferred, but entry is valid only after confirmation.",
  structures: ["240", "60", "15", "5"].map((timeframe) => ({
    timeframe,
    bias: "bullish",
    last_close: 100,
    atr: 2,
    swing_highs: [],
    swing_lows: [],
    events: [],
    summary: "Higher swing highs and higher swing lows.",
  })),
  zones: [
    {
      id: "support",
      timeframe: "15",
      kind: "support",
      lower: 98,
      upper: 99,
      start_time: "2026-06-12T08:00:00Z",
      end_time: "2026-06-12T10:00:00Z",
      status: "active",
      strength: "high",
      touches: 3,
      rationale: "Three reactions.",
    },
  ],
  trend_lines: [],
  scenarios: [
    {
      direction: "long",
      status: "primary",
      quality: "high",
      entry_zone: { lower: 98, upper: 99 },
      trigger: "Wait for a 5m rejection and a close back above the entry zone.",
      invalidation_price: 97,
      targets: [{ label: "TP1", price: 102, reward_risk: 2.33 }],
      evidence: ["60 structure is bullish.", "15 structure is bullish."],
      conflicts: [],
    },
    {
      direction: "short",
      status: "watch",
      quality: "low",
      entry_zone: { lower: 101, upper: 102 },
      trigger: "Wait for a 5m rejection and a close back below the entry zone.",
      invalidation_price: 103,
      targets: [{ label: "TP1", price: 99, reward_risk: 1.67 }],
      evidence: [],
      conflicts: ["60 structure is bullish."],
    },
  ],
  methodology_note: "Geometry is deterministic.",
};

const market: Market = {
  rank: 1,
  symbol: "BTCUSDT",
  base_coin: "BTC",
  last_price: 100,
  turnover_24h_usdt: 1_000_000_000,
  open_interest_usdt: 500_000_000,
  spread_bps: 0.5,
  funding_rate_pct: 0.01,
  price_change_24h_pct: 1,
  launch_time: "2020-01-01T00:00:00Z",
  listing_age_days: 2000,
  tick_size: 0.1,
};

describe("Market analysis details", () => {
  it("shows structure, zones, and conditional scenarios", () => {
    render(<Analysis analysis={analysis} market={market} />);

    expect(screen.getByText("КАРТА РЫНКА")).toBeInTheDocument();
    expect(screen.getByText("Поддержка")).toBeInTheDocument();
    expect(screen.getByText("ОСНОВНОЙ")).toBeInTheDocument();
    expect(screen.getByText("97")).toBeInTheDocument();
    expect(screen.getAllByText(/Триггер:/)).toHaveLength(2);
  });

  it("shows when available margin caps the requested risk size", async () => {
    vi.mocked(api.positionSize).mockResolvedValueOnce({
      requested_risk_usdt: 2.5,
      risk_usdt: 1.4,
      effective_risk_percent: 0.14,
      stop_distance_percent: 0.07,
      quantity: 0.03,
      notional_usdt: 2_000,
      estimated_margin_usdt: 1_000,
      margin_utilization_percent: 100,
      binding_constraint: "margin",
    });

    render(<BottomDesk analysis={analysis} market={market} />);

    expect(
      await screen.findByText(/Размер ограничен доступной маржой/),
    ).toBeInTheDocument();
    expect(screen.getByText("МАРЖА")).toHaveClass("danger");
  });
});
