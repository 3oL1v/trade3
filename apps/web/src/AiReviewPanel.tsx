import { BrainCircuit, CheckCircle2, Clock3, ShieldAlert } from "lucide-react";
import { compactUsd } from "./format";
import type { AiMarketReview, MarketFlowSnapshot } from "./types";

const verdictLabel = {
  long_candidate: "LONG CANDIDATE",
  short_candidate: "SHORT CANDIDATE",
  wait: "WAIT",
};

const convictionLabel = {
  low: "НИЗКАЯ ЯСНОСТЬ",
  medium: "СРЕДНЯЯ ЯСНОСТЬ",
  high: "ВЫСОКАЯ ЯСНОСТЬ",
};

export function AiReviewPanel({
  flow,
  loading,
  review,
}: {
  flow: MarketFlowSnapshot | null;
  loading: boolean;
  review: AiMarketReview | null;
}) {
  return (
    <section className="ai-review panel">
      <header className="ai-review-header">
        <div>
          <BrainCircuit size={15} />
          <span>ЛОКАЛЬНЫЙ AI-АНАЛИТИК</span>
        </div>
        <div className="ai-review-state">
          {review && <span>{review.model}</span>}
          {review?.status === "ready" && <span>{review.runtime_ms} ms</span>}
          <strong className={review?.status ?? "loading"}>
            {loading && !review
              ? "АНАЛИЗ..."
              : review?.status === "ready"
                ? "OLLAMA READY"
                : review?.status === "rejected"
                  ? "РАЗБОР ОТКЛОНЁН"
                  : "OLLAMA OFFLINE"}
          </strong>
        </div>
      </header>
      <FlowStrip flow={review?.market_flow ?? flow} tiedToReview={Boolean(review?.market_flow)} />
      {!review ? (
        <div className="ai-review-loading">
          {loading ? "Модель сопоставляет структуру и условные сценарии..." : "AI-разбор ещё не получен."}
        </div>
      ) : (
        <>
          <div className="ai-review-summary">
            <span className={`ai-verdict ${review.verdict}`}>
              {verdictLabel[review.verdict]}
            </span>
            <strong>{review.headline}</strong>
            <em>{convictionLabel[review.conviction]}</em>
          </div>
          <div className="ai-review-grid">
            <ReviewColumn title="ТЕЗИС" icon={<BrainCircuit size={12} />}>
              <p>{review.thesis}</p>
            </ReviewColumn>
            <ReviewColumn title="ФАКТОРЫ ЗА" icon={<CheckCircle2 size={12} />}>
              <ReviewList items={review.confirmations} empty="Явных подтверждений нет." />
            </ReviewColumn>
            <ReviewColumn title="ФАКТОРЫ ПРОТИВ" icon={<ShieldAlert size={12} />}>
              <ReviewList
                items={review.counterarguments}
                empty="Контраргументы не указаны."
              />
            </ReviewColumn>
            <ReviewColumn title="ДОЖДАТЬСЯ" icon={<Clock3 size={12} />}>
              <ReviewList items={review.wait_for} empty="Условия ожидания не указаны." />
            </ReviewColumn>
          </div>
          <footer className="ai-review-footer">
            AI интерпретирует свечную структуру и снимок потока Bybit. Он не меняет
            уровни, не видит новости и внешнюю агрегированную тепловую карту и не
            размещает ордера.
          </footer>
        </>
      )}
    </section>
  );
}

function FlowStrip({
  flow,
  tiedToReview,
}: {
  flow: MarketFlowSnapshot | null;
  tiedToReview: boolean;
}) {
  if (!flow) {
    return <div className="flow-strip loading">Загрузка стакана и потока сделок...</div>;
  }
  const book10 = flow.orderbook_bands.find((item) => item.distance_bps === 10);
  const book25 = flow.orderbook_bands.find((item) => item.distance_bps === 25);
  const liquidations15 = flow.liquidations.find((item) => item.window_minutes === 15);
  return (
    <div className="flow-strip">
      <FlowMetric
        label={`СТАКАН 10 BPS${tiedToReview ? " / AI" : ""}`}
        tone={tone(book10?.imbalance ?? 0)}
        value={imbalance(book10?.imbalance ?? 0)}
        note={`${bookSide(book10?.imbalance ?? 0)}${book10?.depth_complete ? "" : " / partial"}`}
      />
      <FlowMetric
        label="СТАКАН 25 BPS"
        tone={tone(book25?.imbalance ?? 0)}
        value={imbalance(book25?.imbalance ?? 0)}
        note={`${bookSide(book25?.imbalance ?? 0)}${book25?.depth_complete ? "" : " / partial"}`}
      />
      <FlowMetric
        label="ТЕЙКЕРЫ 60С"
        tone={tone(flow.trade_flow.imbalance)}
        value={imbalance(flow.trade_flow.imbalance)}
        note={`${flow.trade_flow.trade_count}${flow.trade_flow.sample_truncated ? "+" : ""} сделок`}
      />
      <FlowMetric
        label="ЛИКВИДАЦИИ 15М"
        tone={tone(liquidations15?.imbalance ?? 0)}
        value={
          liquidations15
            ? `$${compactUsd(
                liquidations15.long_liquidated_usdt +
                  liquidations15.short_liquidated_usdt,
              )}`
            : "—"
        }
        note={
          liquidations15
            ? `LONG ${compactUsd(liquidations15.long_liquidated_usdt)} / SHORT ${compactUsd(
                liquidations15.short_liquidated_usdt,
              )}`
            : "нет данных"
        }
      />
      <FlowMetric
        label="СПРЕД"
        tone="neutral"
        value={`${flow.spread_bps.toFixed(2)} bps`}
        note="REST snapshot"
      />
    </div>
  );
}

function FlowMetric({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: "positive" | "negative" | "neutral";
}) {
  return (
    <div className={`flow-metric ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function imbalance(value: number): string {
  const percent = value * 100;
  return `${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
}

function tone(value: number): "positive" | "negative" | "neutral" {
  if (value > 0.1) return "positive";
  if (value < -0.1) return "negative";
  return "neutral";
}

function bookSide(value: number): string {
  if (value > 0.1) return "bid depth";
  if (value < -0.1) return "ask depth";
  return "balanced";
}

function ReviewColumn({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="ai-review-column">
      <h3>
        {icon}
        {title}
      </h3>
      {children}
    </div>
  );
}

function ReviewList({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p>{empty}</p>;
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
