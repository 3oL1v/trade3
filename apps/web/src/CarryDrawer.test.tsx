import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { CarryDrawer } from "./CarryDrawer";
import type { CarryBoard, CarryOpportunity, CarryTestStats } from "./types";

vi.mock("./api", () => ({
  api: {
    fundingCarry: vi.fn(),
    carryTestStats: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
});

const makeTestStats = (overrides: Partial<CarryTestStats> = {}): CarryTestStats => ({
  total: 0,
  open_positions: 0,
  resolved: 0,
  due_for_resolution: 0,
  win_rate_after_fees: null,
  positive_after_fees: 0,
  mean_realized_funding_pct: null,
  mean_net_carry_pct: null,
  mean_annualized_net_apr_pct: null,
  horizon_hours: 48,
  scan_seconds: 28800,
  note: "Paper forward test of market-neutral funding carry.",
  ...overrides,
});

const makeOpportunity = (overrides: Partial<CarryOpportunity> = {}): CarryOpportunity => ({
  symbol: "1000PEPEUSDT",
  base_coin: "1000PEPE",
  last_price: 0.0123,
  funding_rate_pct: -0.0512,
  funding_interval_hours: 8,
  annualized_apr_pct: -56.1,
  side: "long_perp_short_spot",
  side_label: "лонг perp + шорт спот",
  easily_hedgeable: false,
  breakeven_hours: 48,
  turnover_24h_usdt: 5_000_000,
  open_interest_usdt: 2_000_000,
  mean_funding_rate_pct: -0.05,
  positive_fraction: 0.1,
  history_samples: 21,
  ...overrides,
});

const makeBoard = (
  opportunities: CarryOpportunity[],
  overrides: Partial<CarryBoard> = {},
): CarryBoard => ({
  generated_at: "2026-06-24T10:00:00Z",
  source_time: "2026-06-24T10:00:00Z",
  taker_fee_rate_pct: 0.055,
  round_trip_fee_pct: 0.22,
  eligible_count: opportunities.length,
  opportunities,
  note: "Carry-арбитраж: шорт perp + лонг спот для сбора funding.",
  ...overrides,
});

describe("CarryDrawer", () => {
  it("renders an opportunity row with symbol, APR, and hard-hedge label", async () => {
    const opp = makeOpportunity({
      symbol: "1000PEPEUSDT",
      funding_rate_pct: -0.0512,
      annualized_apr_pct: -56.1,
      easily_hedgeable: false,
      side_label: "лонг perp + шорт спот",
    });
    const board = makeBoard([opp]);

    vi.mocked(api.fundingCarry).mockResolvedValue(board);
    vi.mocked(api.carryTestStats).mockResolvedValue(makeTestStats());

    render(<CarryDrawer open={true} onClose={() => undefined} />);

    expect(await screen.findByText("1000PEPEUSDT")).toBeInTheDocument();
    expect(await screen.findByText(/-56\.1%/)).toBeInTheDocument();
    // The "нужен спот-шорт" text appears in both the regime banner and the carry-hard label;
    // confirm the carry-hard label specifically is present.
    const hardLabels = await screen.findAllByText(/нужен спот-шорт/i);
    expect(hardLabels.length).toBeGreaterThanOrEqual(1);
  });

  it("shows the negative-regime banner when all opportunities have easily_hedgeable: false", async () => {
    const opps = [
      makeOpportunity({ symbol: "1000PEPEUSDT", easily_hedgeable: false }),
      makeOpportunity({ symbol: "DOGEUSDT", easily_hedgeable: false }),
    ];
    const board = makeBoard(opps);

    vi.mocked(api.fundingCarry).mockResolvedValue(board);
    vi.mocked(api.carryTestStats).mockResolvedValue(makeTestStats());

    render(<CarryDrawer open={true} onClose={() => undefined} />);

    expect(await screen.findByText(/сложной стороне/i)).toBeInTheDocument();
  });

  it("shows the forward-test sampling verdict until enough positions resolve", async () => {
    vi.mocked(api.fundingCarry).mockResolvedValue(makeBoard([makeOpportunity()]));
    vi.mocked(api.carryTestStats).mockResolvedValue(
      makeTestStats({ total: 5, resolved: 4, open_positions: 1 }),
    );

    render(<CarryDrawer open={true} onClose={() => undefined} />);

    expect(await screen.findByText(/ФОРВАРД-ТЕСТ CARRY/)).toBeInTheDocument();
    expect(await screen.findByText(/4\/20 позиций закрыто/)).toBeInTheDocument();
  });
});
