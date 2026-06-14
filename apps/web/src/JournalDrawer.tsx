import { AlertTriangle, BookOpen, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { moscowTime, price } from "./format";
import type { JournalSignal, JournalStats } from "./types";

interface JournalDrawerProps {
  open: boolean;
  stats: JournalStats | null;
  onClose: () => void;
}

const outcomeLabels: Record<string, string> = {
  stop_before_target: "STOP ДО ЦЕЛИ",
  stop_after_target: "STOP ПОСЛЕ ЦЕЛИ",
  target_complete: "ЦЕЛИ ВЫПОЛНЕНЫ",
  expired_without_entry: "ВХОД НЕ ДАН",
  expired_active: "ИСТЁК СРОК",
  invalidated_before_entry: "ИНВАЛИДАЦИЯ ДО ВХОДА",
  missed_at_recording: "ВХОД УПУЩЕН",
  ambiguous: "НЕОДНОЗНАЧНО",
};

export function JournalDrawer({ open, stats, onClose }: JournalDrawerProps) {
  const [signals, setSignals] = useState<JournalSignal[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let active = true;
    const load = () => {
      void api
        .journalSignals(100)
        .then((result) => {
          if (active) {
            setSignals(result.signals);
            setError(null);
          }
        })
        .catch((reason) => {
          if (active) {
            setError(reason instanceof Error ? reason.message : "Журнал недоступен");
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
  const totalCost =
    stats?.average_fee_cost_r == null || stats.average_slippage_cost_r == null
      ? null
      : stats.average_fee_cost_r + stats.average_slippage_cost_r;

  return (
    <div className="journal-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        aria-label="Журнал сигналов"
        className="journal-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="journal-header">
          <div><BookOpen size={15} /><strong>ЖУРНАЛ СИГНАЛОВ</strong></div>
          <button aria-label="Закрыть журнал" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>
        <div className="journal-stats">
          <Stat label="Всего сигналов" value={stats?.total_signals ?? 0} />
          <Stat
            label="Baseline выборка"
            value={`${stats?.resolved_trades ?? 0}/${stats?.minimum_sample_size ?? 100}`}
          />
          <Stat
            label="Net win rate"
            value={percent(stats?.net_win_rate)}
          />
          <Stat
            label="Expectancy"
            value={signedR(stats?.expectancy_r)}
          />
          <Stat
            label="Profit factor"
            value={stats?.profit_factor == null ? "—" : stats.profit_factor.toFixed(2)}
          />
          <Stat
            label="Max drawdown"
            value={stats?.max_drawdown_r == null ? "—" : `${stats.max_drawdown_r.toFixed(2)}R`}
          />
        </div>
        <div className="journal-note">
          <AlertTriangle size={13} />
          <span>
            Baseline: весь объём до первого TP1 или стопа; taker{" "}
            {stats?.taker_fee_rate_pct.toFixed(3) ?? "0.055"}% за сторону,
            проскальзывание {stats?.slippage_bps.toFixed(1) ?? "2.0"} bps за исполнение.
            Funding не включён. Средние издержки: {totalCost == null ? "—" : `${totalCost.toFixed(3)}R`}.
          </span>
        </div>
        {stats && !stats.sample_sufficient && (
          <div className="journal-sample-warning">
            Выборка недостаточна для увеличения риска по score.
          </div>
        )}
        {error && <div className="journal-error">{error}</div>}
        <div className="journal-table">
          <div className="journal-row journal-columns">
            <span>Время / рынок</span><span>План</span><span>Исход</span><span>NET / MFE</span>
          </div>
          {signals.map((signal) => (
            <div className="journal-row" key={signal.id}>
              <div>
                <strong>{signal.symbol}</strong>
                <small>{moscowTime(signal.signal_at)} · {signal.direction.toUpperCase()}</small>
              </div>
              <div>
                <strong>{signal.lifecycle_state.toUpperCase()}</strong>
                <small>{price(signal.entry_price)} / stop {price(signal.stop_price)}</small>
              </div>
              <div>
                <strong className={signal.outcome === "ambiguous" ? "warning" : ""}>
                  {signal.outcome ? outcomeLabels[signal.outcome] ?? signal.outcome : "—"}
                </strong>
                <small>{signal.target_hits.map((hit) => hit.label).join(", ") || "целей нет"}</small>
              </div>
              <div>
                <strong className={netClass(signal.net_result_r)}>
                  {signedR(signal.net_result_r)}
                </strong>
                <small>
                  MFE {signal.mfe_r.toFixed(2)}R · cost {signalCost(signal)}
                </small>
              </div>
            </div>
          ))}
          {!signals.length && !error && (
            <div className="journal-empty">
              Подтверждённых сигналов пока нет. Журнал не записывает ожидание отката и
              watch-сетапы.
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function percent(value: number | null | undefined) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function signedR(value: number | null | undefined) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function signalCost(signal: JournalSignal) {
  if (signal.fee_cost_r == null || signal.slippage_cost_r == null) return "—";
  return `${(signal.fee_cost_r + signal.slippage_cost_r).toFixed(3)}R`;
}

function netClass(value: number | null) {
  if (value == null) return "";
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}
