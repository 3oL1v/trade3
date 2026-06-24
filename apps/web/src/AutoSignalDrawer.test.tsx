import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { AutoSignalDrawer } from "./AutoSignalDrawer";
import type { AutoSignal, AutoSignalStats } from "./types";

vi.mock("./api", () => ({
  api: {
    autoSignals: vi.fn(),
    autoSignalStats: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
});

const makeStats = (overrides: Partial<AutoSignalStats> = {}): AutoSignalStats => ({
  total: 10,
  longs: 5,
  shorts: 3,
  neutrals: 2,
  directional: 8,
  pending_resolution: 4,
  due_for_resolution: 0,
  resolved: 4,
  directional_resolved: 4,
  win_rate: null,
  average_return_pct: null,
  benchmark_resolved: 0,
  average_excess_return_pct: null,
  beat_benchmark_rate: null,
  coin_toss_z: null,
  by_symbol: [],
  horizon_hours: 24,
  scan_seconds: 1800,
  note: "Forward-test note.",
  ...overrides,
});

const makeSignal = (overrides: Partial<AutoSignal> = {}): AutoSignal => ({
  id: 1,
  symbol: "BTCUSDT",
  direction: "long",
  decision_price: 65000,
  generated_at: "2026-06-24T10:00:00Z",
  recorded_at: "2026-06-24T10:01:00Z",
  outcome_price: null,
  outcome_at: null,
  forward_return_pct: null,
  benchmark_symbol: "BTCUSDT",
  benchmark_price: null,
  benchmark_outcome_price: null,
  benchmark_return_pct: null,
  excess_return_pct: null,
  ...overrides,
});

describe("AutoSignalDrawer", () => {
  it("renders pending verdict banner when directional_resolved < 30", async () => {
    const stats = makeStats({ directional_resolved: 4 });
    const signals = [makeSignal(), makeSignal({ id: 2, symbol: "ETHUSDT", direction: "short" })];

    vi.mocked(api.autoSignals).mockResolvedValue({ signals });
    vi.mocked(api.autoSignalStats).mockResolvedValue(stats);

    render(<AutoSignalDrawer open={true} onClose={() => undefined} />);

    expect(await screen.findByText(/4\/30/)).toBeInTheDocument();
    expect(await screen.findByText(/Идёт набор выборки/)).toBeInTheDocument();
  });

  it("renders a resolved signal row and shows Edge-не-обнаружен verdict when |z| < 2", async () => {
    const stats = makeStats({
      directional_resolved: 40,
      win_rate: 0.5,
      coin_toss_z: 0.0,
      resolved: 40,
    });
    const signals = [
      makeSignal({
        id: 10,
        symbol: "SOLUSDT",
        direction: "long",
        forward_return_pct: 0.032,
        outcome_price: 145,
        outcome_at: "2026-06-25T10:00:00Z",
      }),
    ];

    vi.mocked(api.autoSignals).mockResolvedValue({ signals });
    vi.mocked(api.autoSignalStats).mockResolvedValue(stats);

    render(<AutoSignalDrawer open={true} onClose={() => undefined} />);

    expect(await screen.findByText("SOLUSDT")).toBeInTheDocument();
    expect(await screen.findByText(/Edge не обнаружен/)).toBeInTheDocument();
    expect(screen.getAllByText(/50%/).length).toBeGreaterThan(0);
  });
});
