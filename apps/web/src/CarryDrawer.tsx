import { Percent, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { moscowTime } from "./format";
import type { CarryBoard, CarryOpportunity, CarryTestStats } from "./types";

export function CarryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [board, setBoard] = useState<CarryBoard | null>(null);
  const [test, setTest] = useState<CarryTestStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    Promise.all([api.fundingCarry(15), api.carryTestStats()])
      .then(([data, testStats]) => {
        setBoard(data);
        setTest(testStats);
        setError(null);
      })
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Carry-данные недоступны");
      });

  useEffect(() => {
    if (!open) return;
    let active = true;
    const tick = () => {
      if (active) void load();
    };
    tick();
    const timer = window.setInterval(tick, 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [open]);

  if (!open) return null;

  const regimeBanner = () => {
    if (!board || board.opportunities.length === 0) {
      return <div className="carry-regime pending">Нет данных по carry.</div>;
    }
    const easy = board.opportunities.filter((o) => o.easily_hedgeable).length;
    if (easy === 0) {
      return (
        <div className="carry-regime negative">
          {
            "Funding в основном отрицательный — carry на сложной стороне (нужен спот-шорт/borrow). Для розницы малопрактично."
          }
        </div>
      );
    }
    if (easy === board.opportunities.length) {
      return (
        <div className="carry-regime positive">
          {"Funding положительный — carry на простой стороне (шорт perp + лонг спот)."}
        </div>
      );
    }
    return (
      <div className="carry-regime neutral">
        {`Смешанный режим: ${easy} из ${board.opportunities.length} на простой стороне (шорт perp + лонг спот).`}
      </div>
    );
  };

  return (
    <div className="journal-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        aria-label="Funding carry"
        className="journal-drawer"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="journal-header">
          <div>
            <Percent size={15} />
            <strong>FUNDING CARRY</strong>
          </div>
          <button aria-label="Закрыть carry" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>
        <div className="journal-stats">
          <Stat label="Кандидатов" value={board?.eligible_count ?? "—"} />
          <Stat label="Комиссия круга" value={pct(board?.round_trip_fee_pct)} />
          <Stat label="Taker fee" value={pct(board?.taker_fee_rate_pct)} />
          <Stat label="Обновлено" value={board ? moscowTime(board.source_time) : "—"} />
        </div>
        {regimeBanner()}
        <div className="carry-forward">
          <div className="carry-forward-head">
            ФОРВАРД-ТЕСТ CARRY · горизонт {test?.horizon_hours ?? "—"}ч
          </div>
          <div className="journal-stats">
            <Stat label="Позиций" value={test?.total ?? 0} />
            <Stat label="Открыто / закрыто" value={`${test?.open_positions ?? 0}/${test?.resolved ?? 0}`} />
            <Stat label="В плюс (после комиссий)" value={pctRate(test?.win_rate_after_fees)} />
            <Stat label="Ср. net carry" value={signedPct(test?.mean_net_carry_pct, 4)} />
            <Stat label="Ср. net APR" value={signedPct(test?.mean_annualized_net_apr_pct, 1)} />
            <Stat label="Ср. собранный funding" value={signedPct(test?.mean_realized_funding_pct, 4)} />
          </div>
          {carryVerdict(test)}
        </div>
        {board && (
          <div className="journal-note">
            <span>{board.note}</span>
          </div>
        )}
        {error && <div className="journal-error">{error}</div>}
        <div className="journal-table">
          <div className="journal-row journal-columns carry-columns">
            <span>Символ</span>
            <span>Funding</span>
            <span>APR</span>
            <span>Сторона</span>
            <span>Стабильность</span>
            <span>Breakeven</span>
          </div>
          {board?.opportunities.map((opp: CarryOpportunity) => (
            <div className="journal-row carry-columns" key={opp.symbol}>
              <div>
                <strong>{opp.symbol}</strong>
                <small>@ {opp.last_price}</small>
              </div>
              <div>
                <strong className={fundingClass(opp.funding_rate_pct)}>
                  {signedPct(opp.funding_rate_pct, 4)}
                </strong>
                <small>/{opp.funding_interval_hours}ч</small>
              </div>
              <div>
                <strong className={fundingClass(opp.annualized_apr_pct)}>
                  {signedPct(opp.annualized_apr_pct, 1)}
                </strong>
              </div>
              <div>
                <span>{opp.side_label}</span>
                {!opp.easily_hedgeable && (
                  <small className="carry-hard">нужен спот-шорт</small>
                )}
              </div>
              <div>
                {opp.positive_fraction != null ? (
                  <>
                    <strong>{(opp.positive_fraction * 100).toFixed(0)}% знак</strong>
                    <small>
                      средн {signedPct(opp.mean_funding_rate_pct, 4)} · n={opp.history_samples}
                    </small>
                  </>
                ) : (
                  <small>—</small>
                )}
              </div>
              <div>
                <span>{opp.breakeven_hours != null ? opp.breakeven_hours + "ч" : "—"}</span>
              </div>
            </div>
          ))}
          {(!board || board.opportunities.length === 0) && !error && (
            <div className="journal-empty">
              {"Carry-кандидатов нет — рынок без выраженного перекоса funding."}
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

function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(2)}%`;
}

function pctRate(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(0)}%`;
}

function carryVerdict(test: CarryTestStats | null) {
  if (!test || test.resolved < 20) {
    return (
      <div className="carry-regime pending">
        {`Идёт набор выборки: ${test?.resolved ?? 0}/20 позиций закрыто. Вывод о реальном carry пока рано.`}
      </div>
    );
  }
  const net = test.mean_net_carry_pct;
  if (net == null) {
    return <div className="carry-regime pending">Нет закрытых позиций с net-результатом.</div>;
  }
  if (net > 0) {
    return (
      <div className="carry-regime positive">
        {`Net carry положительный после комиссий: ${signedPct(test.mean_net_carry_pct, 4)} за ${test.horizon_hours}ч (≈${signedPct(test.mean_annualized_net_apr_pct, 1)} APR). Это до базис-дрейфа и borrow.`}
      </div>
    );
  }
  return (
    <div className="carry-regime negative">
      {`Net carry отрицательный после комиссий: ${signedPct(test.mean_net_carry_pct, 4)}. Funding не покрывает издержки круга.`}
    </div>
  );
}

function signedPct(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function fundingClass(value: number): string {
  return value > 0 ? "positive" : value < 0 ? "negative" : "";
}
