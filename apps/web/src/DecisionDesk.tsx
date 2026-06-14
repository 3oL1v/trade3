import {
  Activity,
  Calculator,
  Check,
  CircleDot,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { compactUsd, price, signed } from "./format";
import type {
  Market,
  MarketAnalysisSnapshot,
  PositionSizeResult,
  TradeScenario,
} from "./types";

const timeframeLabel: Record<string, string> = {
  "5": "5м",
  "15": "15м",
  "60": "1ч",
  "240": "4ч",
};

const biasLabel = {
  bullish: "Восходящая",
  bearish: "Нисходящая",
  range: "Диапазон",
  insufficient: "Недостаточно данных",
};

const zoneLabel: Record<string, string> = {
  support: "Поддержка",
  resistance: "Сопротивление",
  bullish_fvg: "Bullish FVG",
  bearish_fvg: "Bearish FVG",
  bullish_order_block: "Bullish OB",
  bearish_order_block: "Bearish OB",
  liquidity_high: "Ликвидность сверху",
  liquidity_low: "Ликвидность снизу",
};

export function Analysis({
  analysis,
  market,
}: {
  analysis: MarketAnalysisSnapshot | null;
  market: Market | null;
}) {
  if (!market) {
    return <aside className="analysis panel empty-state">Рынок ещё не загружен</aside>;
  }
  if (!analysis) {
    return <aside className="analysis panel empty-state">Строим карту рынка...</aside>;
  }
  const preferred = analysis.scenarios.find(
    (scenario) => scenario.direction === analysis.preferred_direction,
  );
  const nearbyZones = [...analysis.zones]
    .sort((left, right) => {
      const leftDistance = Math.abs((left.lower + left.upper) / 2 - analysis.last_price);
      const rightDistance = Math.abs((right.lower + right.upper) / 2 - analysis.last_price);
      return leftDistance - rightDistance;
    })
    .slice(0, 6);

  return (
    <aside className="analysis panel">
      <div className="section-title">
        <span>КАРТА РЫНКА</span>
        <CircleDot size={13} />
      </div>
      <div className="setup-name">
        <div>
          <strong>{market.symbol}</strong>
          <small>МУЛЬТИТАЙМФРЕЙМ-АНАЛИЗ</small>
        </div>
        <span className={`direction ${analysis.preferred_direction}`}>
          {analysis.preferred_direction === "neutral"
            ? "NO EDGE"
            : analysis.preferred_direction.toUpperCase()}
        </span>
      </div>
      <div className="analysis-decision">
        <small>ТЕКУЩИЙ ВЫВОД</small>
        <p>{translateDecision(analysis.decision)}</p>
      </div>
      <div className="structure-grid">
        {analysis.structures.map((structure) => (
          <div className={`structure-cell ${structure.bias}`} key={structure.timeframe}>
            <span>{timeframeLabel[structure.timeframe] ?? structure.timeframe}</span>
            <strong>{biasLabel[structure.bias]}</strong>
            <small>
              {structure.events[0]?.kind.toUpperCase() ?? "без свежего BOS/CHOCH"}
            </small>
          </div>
        ))}
      </div>
      <Metric label="Цена" value={price(market.last_price)} />
      <Metric label="Спред" value={`${market.spread_bps.toFixed(2)} bps`} />
      <Metric
        label="Funding"
        value={`${signed(market.funding_rate_pct, 4)}%`}
        tone={market.funding_rate_pct > 0 ? "red" : "green"}
      />
      <Metric label="Open interest" value={`$${compactUsd(market.open_interest_usdt)}`} />
      <div className="zones-list">
        <h3>БЛИЖАЙШИЕ ЗОНЫ</h3>
        {nearbyZones.map((zone) => (
          <div className={`zone-row ${zone.kind}`} key={zone.id}>
            <span>
              {zoneLabel[zone.kind]}
              <small>{timeframeLabel[zone.timeframe] ?? zone.timeframe}</small>
            </span>
            <strong>
              {price(zone.lower)}–{price(zone.upper)}
            </strong>
          </div>
        ))}
      </div>
      <div className="scenario-stack">
        {analysis.scenarios.map((scenario) => (
          <ScenarioCard
            key={scenario.direction}
            scenario={scenario}
            preferred={scenario === preferred}
          />
        ))}
      </div>
      <div className="disclaimer">
        Геометрия рассчитана алгоритмами. Качество сценария не является вероятностью
        выигрыша. Исполнение только вручную.
      </div>
    </aside>
  );
}

function ScenarioCard({
  scenario,
  preferred,
}: {
  scenario: TradeScenario;
  preferred: boolean;
}) {
  return (
    <article className={`scenario-card ${scenario.direction} ${preferred ? "preferred" : ""}`}>
      <header>
        <strong>{scenario.direction.toUpperCase()}</strong>
        <span>{preferred ? "ОСНОВНОЙ" : "АЛЬТЕРНАТИВА"}</span>
        <em>{qualityLabel(scenario.quality)}</em>
      </header>
      <Metric
        label="Зона входа"
        value={`${price(scenario.entry_zone.lower)}–${price(scenario.entry_zone.upper)}`}
      />
      <Metric label="Инвалидация / SL" value={price(scenario.invalidation_price)} tone="red" />
      <p className="scenario-trigger">{translateTrigger(scenario.trigger)}</p>
      <div className="scenario-targets">
        {scenario.targets.map((target) => (
          <span key={target.label}>
            {target.label} <strong>{price(target.price)}</strong> <em>{target.reward_risk}R</em>
          </span>
        ))}
      </div>
      <div className="scenario-evidence">
        {scenario.evidence.map((item) => (
          <p className="positive" key={item}>
            + {translateEvidence(item)}
          </p>
        ))}
        {scenario.conflicts.map((item) => (
          <p className="negative" key={item}>
            − {translateEvidence(item)}
          </p>
        ))}
      </div>
    </article>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={tone}>{value}</strong>
    </div>
  );
}

export function BottomDesk({
  analysis,
  market,
}: {
  analysis: MarketAnalysisSnapshot | null;
  market: Market | null;
}) {
  const scenario = useMemo(
    () =>
      analysis?.scenarios.find(
        (item) => item.direction === analysis.preferred_direction,
      ) ?? null,
    [analysis],
  );
  const marketEntry = market?.last_price ?? 0;
  const referenceEntry = scenario
    ? (scenario.entry_zone.lower + scenario.entry_zone.upper) / 2
    : marketEntry;
  const referenceStop = scenario?.invalidation_price ?? 0;
  const [equity, setEquity] = useState(1000);
  const [risk, setRisk] = useState(0.25);
  const [leverage, setLeverage] = useState(2);
  const [entry, setEntry] = useState(referenceEntry);
  const [stop, setStop] = useState(referenceStop);
  const [result, setResult] = useState<PositionSizeResult | null>(null);

  useEffect(() => {
    setEntry(referenceEntry);
    setStop(referenceStop);
  }, [market?.symbol, referenceEntry, referenceStop]);

  useEffect(() => {
    if (!entry || !stop || entry === stop) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => {
      void api
        .positionSize({
          equity_usdt: equity,
          risk_percent: risk,
          entry_price: entry,
          stop_price: stop,
          leverage,
        })
        .then(setResult)
        .catch(() => setResult(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [entry, equity, leverage, risk, stop]);

  const marginCapped = result?.binding_constraint === "margin";
  const checks = [
    ["Есть направление на 1ч и 15м", Boolean(scenario?.status === "primary")],
    ["Вход опирается на структурную зону", Boolean(scenario?.evidence.length)],
    ["Определена точка инвалидации", Boolean(scenario?.invalidation_price)],
    ["Есть цель минимум 1.5R", Boolean(scenario?.targets.some((target) => target.reward_risk >= 1.5))],
    ["Получено подтверждение триггера на 5м", false],
    ["Новости и ликвидационная карта проверены", false],
    ["Маржа не превышает капитал", Boolean(result && result.estimated_margin_usdt <= equity)],
  ] as const;

  return (
    <section className="bottom-desk">
      <div className="checklist panel">
        <div className="section-title">
          <span>РУЧНОЙ ЧЕК-ЛИСТ</span>
          <ShieldCheck size={14} />
        </div>
        <div className="check-grid">
          {checks.map(([label, checked]) => (
            <label key={label}>
              <span className={`check ${checked ? "checked" : ""}`}>
                {checked && <Check size={11} />}
              </span>
              {label}
            </label>
          ))}
        </div>
        <strong className="manual-only">MANUAL EXECUTION ONLY</strong>
      </div>
      <div className="risk-panel panel">
        <div className="section-title">
          <span>РАСЧЁТ РИСКА ПО СЦЕНАРИЮ</span>
          <Calculator size={14} />
        </div>
        <div className="risk-content">
          <div className="risk-inputs">
            <NumberField label="Капитал, USDT" value={equity} onChange={setEquity} />
            <NumberField label="Риск, %" value={risk} onChange={setRisk} step={0.1} max={0.5} />
            <NumberField label="Плечо" value={leverage} onChange={setLeverage} step={1} max={3} />
            <NumberField label="Вход" value={entry} onChange={setEntry} />
            <NumberField label="Стоп" value={stop} onChange={setStop} />
          </div>
          <div className="risk-results">
            <Result label="Риск" value={result ? `$${price(result.risk_usdt)}` : "—"} />
            <Result
              label="Стоп"
              value={result ? `${result.stop_distance_percent.toFixed(2)}%` : "—"}
            />
            <Result
              label="Объём позиции"
              value={result ? `$${price(result.notional_usdt)}` : "—"}
              accent
            />
            <Result label="Количество" value={result ? price(result.quantity) : "—"} />
            <Result
              label="Маржа"
              value={result ? `$${price(result.estimated_margin_usdt)}` : "—"}
            />
            <Result
              label="Ограничение"
              value={
                result
                  ? result.binding_constraint === "margin"
                    ? "МАРЖА"
                    : "РИСК"
                  : "—"
              }
              danger={marginCapped}
            />
          </div>
        </div>
        <p className={`risk-note ${marginCapped ? "capped" : ""}`}>
          <Activity size={12} />
          {marginCapped && result
            ? `Размер ограничен доступной маржой. Фактический риск ${result.effective_risk_percent.toFixed(3)}% вместо ${risk.toFixed(3)}%.`
            : scenario
            ? "Вход и стоп взяты из выбранного сценария. Подтверждение входа остаётся ручным."
            : "Направленного сценария нет. Не использовать калькулятор как основание для сделки."}
        </p>
      </div>
    </section>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = 0.01,
  max,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  max?: number;
}) {
  return (
    <label className="number-field">
      <span>{label}</span>
      <input
        max={max}
        min={0}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={Number.isFinite(value) ? value : 0}
      />
    </label>
  );
}

function Result({
  label,
  value,
  accent,
  danger,
}: {
  label: string;
  value: string;
  accent?: boolean;
  danger?: boolean;
}) {
  const className = danger ? "danger" : accent ? "accent" : "";
  return (
    <div className="result">
      <span>{label}</span>
      <strong className={className}>{value}</strong>
    </div>
  );
}

function translateDecision(value: string): string {
  if (value.startsWith("Long context")) {
    return "Контекст склоняется к лонгу, но вход допустим только после подтверждения на 5м.";
  }
  if (value.startsWith("Short context")) {
    return "Контекст склоняется к шорту, но вход допустим только после подтверждения на 5м.";
  }
  return "Явного преимущества нет. Оба сценария остаются условными, лучше ждать.";
}

function translateTrigger(value: string): string {
  return value.includes("above")
    ? "Триггер: реакция внутри зоны и закрытие 5м обратно выше неё."
    : "Триггер: реакция внутри зоны и закрытие 5м обратно ниже неё.";
}

function translateEvidence(value: string): string {
  const structure = value.match(/^(\d+) structure is (bullish|bearish)\.$/);
  if (structure) {
    const [, timeframe, bias] = structure;
    return `${timeframeLabel[timeframe] ?? timeframe}: структура ${
      bias === "bullish" ? "восходящая" : "нисходящая"
    }`;
  }

  const entry = value.match(/^Entry references (\d+) ([a-z_]+)\.$/);
  if (entry) {
    const [, timeframe, kind] = entry;
    return `вход опирается на «${zoneLabel[kind] ?? kind}» (${
      timeframeLabel[timeframe] ?? timeframe
    })`;
  }

  if (value === "No nearby active structural zone supports the entry.") {
    return "рядом нет активной структурной зоны для входа";
  }
  return value;
}

function qualityLabel(value: TradeScenario["quality"]): string {
  return {
    low: "СЛАБЫЙ",
    medium: "СРЕДНИЙ",
    high: "СИЛЬНЫЙ",
  }[value];
}
