import { ClipboardList, X } from "lucide-react";
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

  useEffect(() => {
    if (!open) return;
    let active = true;
    const load = () => {
      void Promise.all([api.decisions(100), api.decisionStats()])
        .then(([list, nextStats]) => {
          if (!active) return;
          setDecisions(list.decisions);
          setStats(nextStats);
          setError(null);
        })
        .catch((reason) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "Журнал решений недоступен");
          }
        });
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open]);

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
          <button aria-label="Закрыть журнал решений" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>
        <div className="journal-stats">
          <Stat label="Всего решений" value={stats?.total ?? 0} />
          <Stat label="Принято" value={stats?.accepted ?? 0} />
          <Stat label="Accept rate" value={percent(stats?.accept_rate)} />
          <Stat label="Long / Short" value={`${stats?.longs ?? 0} / ${stats?.shorts ?? 0}`} />
          <Stat
            label="Совпало с AI"
            value={`${stats?.agreed_with_ai ?? 0}/${stats?.ai_comparable ?? 0}`}
          />
          <Stat label="Agreement" value={percent(stats?.agreement_rate)} />
        </div>
        <div className="journal-note">
          <span>
            Ручные дискреционные решения. Отдельно от выведенного из работы журнала
            стратегий. Исходы сделок пока не отслеживаются — это фундамент под shadow-тест.
          </span>
        </div>
        {error && <div className="journal-error">{error}</div>}
        <div className="journal-table">
          <div className="journal-row journal-columns decision-columns">
            <span>Время / рынок</span>
            <span>Решение</span>
            <span>AI / совпадение</span>
            <span>Заметка</span>
          </div>
          {decisions.map((decision) => (
            <div className="journal-row decision-columns" key={decision.id}>
              <div>
                <strong>{decision.symbol}</strong>
                <small>{moscowTime(decision.recorded_at)}</small>
              </div>
              <div>
                <strong className={`decision-tag ${decision.action}`}>
                  {actionLabels[decision.action] ?? decision.action.toUpperCase()}
                </strong>
                <small>
                  {decision.direction === "none" ? "—" : decision.direction.toUpperCase()}
                </small>
              </div>
              <div>
                <strong>
                  {decision.ai_verdict ? verdictLabels[decision.ai_verdict] ?? decision.ai_verdict : "—"}
                </strong>
                <small className={agreementClass(decision.agreed_with_ai)}>
                  {agreementLabel(decision.agreed_with_ai)}
                </small>
              </div>
              <div>
                <small>{decision.note ?? "—"}</small>
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

function agreementLabel(value: boolean | null) {
  if (value === null) return "без AI";
  return value ? "совпало" : "расходится";
}

function agreementClass(value: boolean | null) {
  if (value === null) return "";
  return value ? "positive" : "negative";
}
