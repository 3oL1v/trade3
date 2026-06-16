import { Activity, Check, ClipboardList, Download, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { moscowTime } from "./format";
import type { ManualDecision, ManualDecisionStats } from "./types";

const actionLabels: Record<string, string> = {
  accept: "ПРИНЯТО",
  reject: "ОТКЛОНЕНО",
  defer: "ОТЛОЖЕНО",
};

const verdictLabels: Record<string, string> = {
  long_candidate: "AI: LONG",
  short_candidate: "AI: SHORT",
  wait: "AI: WAIT",
};

export function DecisionJournalDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [decisions, setDecisions] = useState<ManualDecision[]>([]);
  const [stats, setStats] = useState<ManualDecisionStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [priceInputs, setPriceInputs] = useState<Record<number, string>>({});

  const load = () =>
    Promise.all([api.decisions(100), api.decisionStats()])
      .then(([list, nextStats]) => {
        setDecisions(list.decisions);
        setStats(nextStats);
        setError(null);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Журнал решений недоступен");
      });

  useEffect(() => {
    if (!open) return;
    let active = true;
    const tick = () => {
      if (active) void load();
    };
    tick();
    const timer = window.setInterval(tick, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open]);

  const fillLivePrice = async (id: number, symbol: string) => {
    try {
      const result = await api.price(symbol);
      setPriceInputs((current) => ({ ...current, [id]: String(result.price) }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось получить цену");
    }
  };

  const resolve = async (id: number) => {
    const price = Number(priceInputs[id]);
    if (!Number.isFinite(price) || price <= 0) return;
    try {
      await api.resolveDecision(id, price);
      setPriceInputs((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось записать исход");
    }
  };

  if (!open) return null;

  return (
    <div className="journal-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        aria-label="Журнал решений"
        className="journal-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="journal-header">
          <div>
            <ClipboardList size={15} />
            <strong>ЖУРНАЛ РЕШЕНИЙ</strong>
          </div>
          <div className="journal-header-actions">
            <a
              aria-label="Скачать журнал решений в CSV"
              className="journal-download"
              href="/v1/decisions.csv"
            >
              <Download size={13} />
              CSV
            </a>
            <button aria-label="Закрыть журнал решений" onClick={onClose} type="button">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="journal-stats">
          <Stat label="Всего решений" value={stats?.total ?? 0} />
          <Stat label="Accept rate" value={percent(stats?.accept_rate)} />
          <Stat label="Agreement с AI" value={percent(stats?.agreement_rate)} />
          <Stat
            label="Исходов записано"
            value={`${stats?.accepts_resolved ?? 0}/${stats?.accepted ?? 0}`}
          />
          <Stat label="Accept win rate" value={percent(stats?.accept_win_rate)} />
          <Stat label="Ср. доходность" value={signedPercent(stats?.average_accept_return_pct)} />
          <Stat label="Бьёт BTC" value={percent(stats?.beat_benchmark_rate)} />
          <Stat label="Ср. alpha vs BTC" value={signedPercent(stats?.average_excess_return_pct)} />
        </div>
        <div className="journal-note">
          <span>
            Ручные дискреционные решения, отдельно от выведенного из работы журнала
            стратегий. Доходность — направленное движение от цены решения до цены исхода,
            до комиссий и без бенчмарка. Это фундамент под shadow-тест, а не P&L.
          </span>
        </div>
        {error && <div className="journal-error">{error}</div>}
        <div className="journal-table">
          <div className="journal-row journal-columns decision-columns">
            <span>Время / рынок</span>
            <span>Решение</span>
            <span>AI / совпадение</span>
            <span>Исход</span>
          </div>
          {decisions.map((decision) => (
            <div className="journal-row decision-columns" key={decision.id}>
              <div>
                <strong>{decision.symbol}</strong>
                <small>{moscowTime(decision.recorded_at)}</small>
                {decision.note && <small className="decision-row-note">{decision.note}</small>}
              </div>
              <div>
                <strong className={`decision-tag ${decision.action}`}>
                  {actionLabels[decision.action] ?? decision.action.toUpperCase()}
                </strong>
                <small>
                  {decision.direction === "none" ? "—" : decision.direction.toUpperCase()}
                  {decision.decision_price != null && ` @ ${decision.decision_price}`}
                </small>
              </div>
              <div>
                <strong>
                  {decision.ai_verdict
                    ? verdictLabels[decision.ai_verdict] ?? decision.ai_verdict
                    : "—"}
                </strong>
                <small className={agreementClass(decision.agreed_with_ai)}>
                  {agreementLabel(decision.agreed_with_ai)}
                </small>
              </div>
              <div>
                {decision.outcome_return_pct != null ? (
                  <>
                    <strong className={returnClass(decision.outcome_return_pct)}>
                      {signedPercent(decision.outcome_return_pct)}
                    </strong>
                    <small className={returnClass(decision.excess_return_pct ?? 0)}>
                      {decision.excess_return_pct != null
                        ? `${signedPercent(decision.excess_return_pct)} vs BTC`
                        : `@ ${decision.outcome_price}`}
                    </small>
                  </>
                ) : (
                  <div className="decision-resolve">
                    <button
                      aria-label={`Подставить текущую цену для решения ${decision.id}`}
                      className="decision-live-btn"
                      onClick={() => void fillLivePrice(decision.id, decision.symbol)}
                      type="button"
                      title="Текущая цена"
                    >
                      <Activity size={13} />
                    </button>
                    <input
                      aria-label={`Цена исхода для решения ${decision.id}`}
                      className="decision-resolve-input"
                      inputMode="decimal"
                      onChange={(event) =>
                        setPriceInputs((current) => ({
                          ...current,
                          [decision.id]: event.target.value,
                        }))
                      }
                      placeholder="цена исхода"
                      type="text"
                      value={priceInputs[decision.id] ?? ""}
                    />
                    <button
                      aria-label={`Записать исход решения ${decision.id}`}
                      className="decision-resolve-btn"
                      onClick={() => void resolve(decision.id)}
                      type="button"
                    >
                      <Check size={13} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {!decisions.length && !error && (
            <div className="journal-empty">
              Решений пока нет. Нажми «Принять / Отклонить / Отложить» в панели решения.
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(0)}%`;
}

function signedPercent(value: number | null | undefined) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function agreementLabel(value: boolean | null) {
  if (value === null) return "без AI";
  return value ? "совпало" : "расходится";
}

function agreementClass(value: boolean | null) {
  if (value === null) return "";
  return value ? "positive" : "negative";
}

function returnClass(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}
