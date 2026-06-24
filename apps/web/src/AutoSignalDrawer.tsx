import { FlaskConical, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { moscowTime } from "./format";
import type { AutoSignal, AutoSignalStats } from "./types";

export function AutoSignalDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [signals, setSignals] = useState<AutoSignal[]>([]);
  const [stats, setStats] = useState<AutoSignalStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.autoSignals(100), api.autoSignalStats()])
      .then(([list, nextStats]) => {
        setSignals(list.signals);
        setStats(nextStats);
        setError(null);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Автотест недоступен");
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

  if (!open) return null;

  const verdictBanner = () => {
    if (!stats || stats.directional_resolved < 30) {
      const n = stats?.directional_resolved ?? 0;
      return (
        <div className="auto-verdict pending">
          {`Идёт набор выборки: ${n}/30 направленных разрешено. Статзначимость пока недоступна.`}
        </div>
      );
    }
    const z = stats.coin_toss_z;
    if (z == null || Math.abs(z) < 2) {
      return (
        <div className="auto-verdict neutral">
          {`Edge не обнаружен: win rate ${percent(stats.win_rate)} статистически неотличим от подбрасывания монеты (z=${zValue(z)}).`}
        </div>
      );
    }
    if (z >= 2) {
      return (
        <div className="auto-verdict positive">
          {`Сигнал значим: win rate ${percent(stats.win_rate)} выше монетки (z=${zValue(z)}). Нужна проверка на издержки.`}
        </div>
      );
    }
    return (
      <div className="auto-verdict negative">
        {`Обратный edge: система значимо хуже монетки (z=${zValue(z)}).`}
      </div>
    );
  };

  return (
    <div className="journal-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        aria-label="Автотест сигналов"
        className="journal-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="journal-header">
          <div>
            <FlaskConical size={15} />
            <strong>АВТОТЕСТ СИГНАЛОВ</strong>
          </div>
          <button aria-label="Закрыть автотест" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>
        <div className="journal-stats">
          <Stat label="Сигналов всего" value={stats?.total ?? 0} />
          <Stat
            label="Long / Short / Neutral"
            value={`${stats?.longs ?? 0}/${stats?.shorts ?? 0}/${stats?.neutrals ?? 0}`}
          />
          <Stat label="Направленных" value={stats?.directional ?? 0} />
          <Stat
            label="Разрешено"
            value={`${stats?.directional_resolved ?? 0}/${stats?.directional ?? 0}`}
          />
          <Stat label="Win rate" value={percent(stats?.win_rate)} />
          <Stat label="Ср. доходность" value={signedPercent(stats?.average_return_pct)} />
          <Stat label="Бьёт BTC" value={percent(stats?.beat_benchmark_rate)} />
          <Stat label="Ср. alpha vs BTC" value={signedPercent(stats?.average_excess_return_pct)} />
          <Stat label="Z vs монетка" value={zValue(stats?.coin_toss_z)} />
        </div>
        {verdictBanner()}
        {stats && stats.by_symbol.length > 0 && (
          <div className="decision-breakdown">
            <div className="decision-breakdown-head">
              <span>Символ</span>
              <span>N</span>
              <span>Win</span>
              <span>Ср. дох.</span>
              <span>Alpha</span>
            </div>
            {stats.by_symbol.map((row) => (
              <div className="decision-breakdown-row" key={row.symbol}>
                <span>{row.symbol}</span>
                <span>{row.resolved}</span>
                <span>{percent(row.win_rate)}</span>
                <span className={returnClass(row.average_return_pct ?? 0)}>
                  {signedPercent(row.average_return_pct)}
                </span>
                <span className={returnClass(row.average_excess_return_pct ?? 0)}>
                  {signedPercent(row.average_excess_return_pct)}
                </span>
              </div>
            ))}
          </div>
        )}
        {stats && (
          <div className="journal-note">
            <span>{stats.note}</span>
          </div>
        )}
        {error && <div className="journal-error">{error}</div>}
        <div className="journal-table">
          <div className="journal-row journal-columns auto-columns">
            <span>Время / рынок</span>
            <span>Направление</span>
            <span>Доходность</span>
            <span>vs BTC</span>
          </div>
          {signals.map((signal) => (
            <div className="journal-row auto-columns" key={signal.id}>
              <div>
                <strong>{signal.symbol}</strong>
                <small>{moscowTime(signal.recorded_at)}</small>
              </div>
              <div>
                <strong className={`dir-tag ${signal.direction}`}>
                  {signal.direction === "long" || signal.direction === "short"
                    ? signal.direction.toUpperCase()
                    : "NEUTRAL"}
                </strong>
                <small>
                  {signal.decision_price != null ? `@ ${signal.decision_price}` : "—"}
                </small>
              </div>
              <div>
                {signal.forward_return_pct != null ? (
                  <strong className={returnClass(signal.forward_return_pct)}>
                    {signedPercent(signal.forward_return_pct)}
                  </strong>
                ) : signal.direction !== "long" && signal.direction !== "short" ? (
                  <small>нет позиции</small>
                ) : (
                  <span className="decision-due-tag">ждёт</span>
                )}
              </div>
              <div>
                {signal.excess_return_pct != null ? (
                  <strong className={returnClass(signal.excess_return_pct)}>
                    {signedPercent(signal.excess_return_pct)}
                  </strong>
                ) : (
                  "—"
                )}
              </div>
            </div>
          ))}
          {!signals.length && !error && (
            <div className="journal-empty">
              {`Автотест ещё не записал сигналы. Сборщик стартует в фоне и снимает направление по вселенной раз в ${stats ? Math.round(stats.scan_seconds / 60) : 30} мин.`}
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

function returnClass(value: number) {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}

function zValue(value: number | null | undefined) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}
