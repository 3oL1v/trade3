import { Check, Clock3, ThumbsDown, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";
import { api } from "./api";
import type {
  AiMarketReview,
  DecisionAction,
  DecisionDirection,
  MarketAnalysisSnapshot,
} from "./types";

type SaveState = "idle" | "saving" | "saved" | "error";

export function DecisionActions({
  symbol,
  analysis,
  aiReview,
  onRecorded,
}: {
  symbol: string;
  analysis: MarketAnalysisSnapshot | null;
  aiReview: AiMarketReview | null;
  onRecorded: () => void;
}) {
  const [note, setNote] = useState("");
  const [state, setState] = useState<SaveState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const ready = analysis !== null;

  const record = async (action: DecisionAction, direction: DecisionDirection) => {
    if (!ready || state === "saving") return;
    setState("saving");
    setMessage(null);
    try {
      const decision = await api.recordDecision({
        symbol,
        action,
        direction,
        ai_verdict: aiReview?.verdict ?? null,
        ai_conviction: aiReview?.conviction ?? null,
        decision_price: analysis?.last_price ?? null,
        snapshot_generated_at: aiReview?.snapshot_generated_at ?? analysis?.generated_at ?? null,
        note: note.trim() || null,
        analysis_snapshot: analysis,
        ai_review: aiReview,
      });
      setState("saved");
      setNote("");
      const tag =
        decision.agreed_with_ai === null
          ? ""
          : decision.agreed_with_ai
            ? " · совпало с AI"
            : " · расходится с AI";
      setMessage(`Записано #${decision.id}${tag}`);
      onRecorded();
    } catch (reason) {
      setState("error");
      setMessage(reason instanceof Error ? reason.message : "Не удалось записать решение");
    }
  };

  return (
    <section className="decision-actions panel">
      <header className="decision-actions-head">
        <span>МОЁ РЕШЕНИЕ ПО {symbol}</span>
        <small>Записывает снимок анализа и AI на момент решения. Ордер не ставится.</small>
      </header>
      <div className="decision-buttons">
        <button
          className="decision-btn accept-long"
          disabled={!ready || state === "saving"}
          onClick={() => void record("accept", "long")}
          type="button"
        >
          <TrendingUp size={14} /> ПРИНЯТЬ LONG
        </button>
        <button
          className="decision-btn accept-short"
          disabled={!ready || state === "saving"}
          onClick={() => void record("accept", "short")}
          type="button"
        >
          <TrendingDown size={14} /> ПРИНЯТЬ SHORT
        </button>
        <button
          className="decision-btn reject"
          disabled={!ready || state === "saving"}
          onClick={() => void record("reject", "none")}
          type="button"
        >
          <ThumbsDown size={14} /> ОТКЛОНИТЬ
        </button>
        <button
          className="decision-btn defer"
          disabled={!ready || state === "saving"}
          onClick={() => void record("defer", "none")}
          type="button"
        >
          <Clock3 size={14} /> ОТЛОЖИТЬ
        </button>
      </div>
      <div className="decision-note-row">
        <input
          className="decision-note"
          maxLength={2000}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Заметка к решению (необязательно)"
          type="text"
          value={note}
        />
        {message && (
          <span className={`decision-message ${state}`}>
            {state === "saved" && <Check size={13} />}
            {message}
          </span>
        )}
      </div>
    </section>
  );
}
