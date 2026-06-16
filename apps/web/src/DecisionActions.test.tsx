import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DecisionActions } from "./DecisionActions";
import type { MarketAnalysisSnapshot } from "./types";

const recordDecision = vi.fn();

vi.mock("./api", () => ({
  api: {
    recordDecision: (...args: unknown[]) => recordDecision(...args),
  },
}));

afterEach(() => {
  cleanup();
  recordDecision.mockReset();
});

const analysis: MarketAnalysisSnapshot = {
  symbol: "BTCUSDT",
  generated_at: "2026-06-12T10:00:00Z",
  last_price: 100000,
  preferred_direction: "neutral",
  decision: "test",
  structures: [],
  zones: [],
  trend_lines: [],
  flags: [],
  scenarios: [],
  methodology_note: "test",
};

it("posts an accept-long decision with the current snapshot", async () => {
  recordDecision.mockResolvedValue({ id: 7, agreed_with_ai: true });
  const onRecorded = vi.fn();
  render(
    <DecisionActions
      symbol="BTCUSDT"
      analysis={analysis}
      aiReview={null}
      onRecorded={onRecorded}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /ПРИНЯТЬ LONG/ }));

  await waitFor(() => expect(recordDecision).toHaveBeenCalledTimes(1));
  const payload = recordDecision.mock.calls[0][0];
  expect(payload.symbol).toBe("BTCUSDT");
  expect(payload.action).toBe("accept");
  expect(payload.direction).toBe("long");
  expect(payload.analysis_snapshot).toEqual(analysis);
  await waitFor(() => expect(onRecorded).toHaveBeenCalled());
  expect(await screen.findByText(/Записано #7/)).toBeInTheDocument();
});

it("disables the buttons until analysis is loaded", () => {
  render(
    <DecisionActions symbol="BTCUSDT" analysis={null} aiReview={null} onRecorded={vi.fn()} />,
  );
  expect(screen.getByRole("button", { name: /ОТКЛОНИТЬ/ })).toBeDisabled();
});
