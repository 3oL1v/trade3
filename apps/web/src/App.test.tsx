import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(cleanup);

vi.mock("./PriceChart", () => ({
  PriceChart: () => <div data-testid="price-chart" />,
}));

vi.mock("./api", () => ({
  api: {
    status: vi.fn().mockResolvedValue({
      state: "running",
      enabled: true,
      journal_enabled: false,
      symbols: ["BTCUSDT"],
      intervals: ["5", "15", "60"],
      started_at: null,
      last_message_at: new Date().toISOString(),
      last_universe_refresh_at: null,
      reconnect_count: 0,
      last_error: null,
      clock_skew_seconds: 0.1,
      clock_synchronized: true,
      ticker_count: 1,
      candle_series_count: 3,
    }),
    universe: vi.fn().mockResolvedValue({
      markets: [
        {
          rank: 1,
          symbol: "BTCUSDT",
          base_coin: "BTC",
          last_price: 100000,
          turnover_24h_usdt: 1000000000,
          open_interest_usdt: 100000000,
          spread_bps: 0.5,
          funding_rate_pct: 0.01,
          price_change_24h_pct: 1,
          launch_time: "2020-01-01T00:00:00Z",
          listing_age_days: 2000,
          tick_size: 0.1,
        },
      ],
    }),
    candles: vi.fn().mockResolvedValue({ candles: [] }),
    analysis: vi.fn().mockResolvedValue({
      symbol: "BTCUSDT",
      generated_at: new Date().toISOString(),
      last_price: 100000,
      preferred_direction: "neutral",
      decision: "No clear directional edge.",
      structures: [],
      zones: [],
      trend_lines: [],
      scenarios: [],
      methodology_note: "test",
    }),
    positionSize: vi.fn(),
    journalStats: vi.fn().mockResolvedValue({
      total_signals: 0,
      pending_entry: 0,
      active: 0,
      closed: 0,
      entered: 0,
      ambiguous: 0,
      expired_without_entry: 0,
      missed_at_recording: 0,
      stop_before_target: 0,
      stop_after_target: 0,
      tp1_hits: 0,
      tp2_hits: 0,
      structure_hits: 0,
      tp1_hit_rate: null,
      average_mfe_r: null,
      average_mae_r: null,
      execution_policy: "manual",
      taker_fee_rate_pct: 0.055,
      slippage_bps: 2,
      resolved_trades: 0,
      net_wins: 0,
      net_losses: 0,
      net_breakeven: 0,
      net_win_rate: null,
      expectancy_r: null,
      profit_factor: null,
      cumulative_net_r: null,
      max_drawdown_r: null,
      average_fee_cost_r: null,
      average_slippage_cost_r: null,
      minimum_sample_size: 100,
      sample_sufficient: false,
      funding_included: false,
      note: "test",
    }),
  },
}));

describe("Trade3 terminal", () => {
  it("shows the manual-only analysis boundary", async () => {
    render(<App />);
    expect(screen.getByText("MANUAL EXECUTION ONLY")).toBeInTheDocument();
    expect(screen.getByText("AI ANALYSIS / MANUAL EXECUTION")).toBeInTheDocument();
    expect(await screen.findByText("КАРТА РЫНКА")).toBeInTheDocument();
    expect(await screen.findByText("BTC")).toBeInTheDocument();
  });

  it("uses the focused chart view by default and can reveal all layers", () => {
    render(<App />);
    const toggle = screen.getByRole("button", { name: "ФОКУС" });

    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: "ВСЕ СЛОИ" })).toHaveClass("active");
  });
});
