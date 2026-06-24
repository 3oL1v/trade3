import {
  AlertTriangle,
  BookOpen,
  ClipboardList,
  Clock3,
  Database,
  FlaskConical,
  Percent,
  RefreshCw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { AiReviewPanel } from "./AiReviewPanel";
import { api } from "./api";
import { AutoSignalDrawer } from "./AutoSignalDrawer";
import { CarryDrawer } from "./CarryDrawer";
import { DecisionActions } from "./DecisionActions";
import { Analysis, BottomDesk } from "./DecisionDesk";
import { DecisionJournalDrawer } from "./DecisionJournalDrawer";
import { ageSeconds, compactUsd, moscowTime, signed } from "./format";
import { JournalDrawer } from "./JournalDrawer";
import { PriceChart } from "./PriceChart";
import type {
  AiMarketReview,
  AutoSignalStats,
  Candle,
  JournalStats,
  LiveEngineStatus,
  ManualDecisionStats,
  Market,
  MarketAnalysisSnapshot,
  MarketFlowSnapshot,
  Timeframe,
} from "./types";

const timeframeLabels: Record<Timeframe, string> = {
  "5": "5м",
  "15": "15м",
  "60": "1ч",
  "240": "4ч",
};

function useClock() {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

export function App() {
  const now = useClock();
  const [status, setStatus] = useState<LiveEngineStatus | null>(null);
  const [markets, setMarkets] = useState<Market[]>([]);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState<Timeframe>("15");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [analysis, setAnalysis] = useState<MarketAnalysisSnapshot | null>(null);
  const [aiReview, setAiReview] = useState<AiMarketReview | null>(null);
  const [aiLoading, setAiLoading] = useState(true);
  const [flow, setFlow] = useState<MarketFlowSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingChart, setLoadingChart] = useState(true);
  const [detailedChart, setDetailedChart] = useState(false);
  const [journalStats, setJournalStats] = useState<JournalStats | null>(null);
  const [journalOpen, setJournalOpen] = useState(false);
  const [decisionStats, setDecisionStats] = useState<ManualDecisionStats | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [autoStats, setAutoStats] = useState<AutoSignalStats | null>(null);
  const [autoOpen, setAutoOpen] = useState(false);
  const [carryOpen, setCarryOpen] = useState(false);

  const refreshDecisionStats = useCallback(() => {
    const pending = api.decisionStats?.();
    if (!pending) return;
    void pending.then(setDecisionStats).catch(() => setDecisionStats(null));
  }, []);

  const refreshAutoStats = useCallback(() => {
    const pending = api.autoSignalStats?.();
    if (!pending) return;
    void pending.then(setAutoStats).catch(() => setAutoStats(null));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextStatus, universe] = await Promise.all([api.status(), api.universe()]);
      setStatus(nextStatus);
      setMarkets(universe.markets);
      setSymbol((current) =>
        universe.markets.some((market) => market.symbol === current)
          ? current
          : (universe.markets[0]?.symbol ?? current),
      );
      setError(null);
      if (nextStatus.journal_enabled) {
        void api
          .journalStats()
          .then(setJournalStats)
          .catch(() => {
            setJournalStats(null);
            setJournalOpen(false);
          });
      } else {
        setJournalStats(null);
        setJournalOpen(false);
      }
      refreshDecisionStats();
      refreshAutoStats();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "API недоступен");
    }
  }, [refreshDecisionStats, refreshAutoStats]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoadingChart(true);
      try {
        const series = await api.candles(symbol, timeframe);
        if (active) setCandles(series.candles);
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Свечи недоступны");
        }
      } finally {
        if (active) setLoadingChart(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol, timeframe]);

  useEffect(() => {
    let active = true;
    setAnalysis(null);
    const load = async () => {
      try {
        const snapshot = await api.analysis(symbol);
        if (active) setAnalysis(snapshot);
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Анализ недоступен");
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol]);

  useEffect(() => {
    let active = true;
    setFlow(null);
    const load = async () => {
      try {
        const snapshot = await api.flow(symbol);
        if (active) setFlow(snapshot);
      } catch {
        if (active) setFlow(null);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol]);

  useEffect(() => {
    let active = true;
    setAiReview(null);
    const load = async () => {
      setAiLoading(true);
      try {
        const review = await api.aiAnalysis(symbol);
        if (active) setAiReview(review);
      } catch {
        if (active) setAiReview(null);
      } finally {
        if (active) setAiLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [symbol]);

  const selectedMarket = markets.find((market) => market.symbol === symbol) ?? null;
  const isLive =
    status?.state === "running" &&
    status.clock_synchronized &&
    (ageSeconds(status.last_message_at) ?? Infinity) < 20;

  return (
    <main className="terminal-shell">
      <Header
        status={status}
        live={isLive}
        now={now}
        journalCount={journalStats?.total_signals ?? null}
        decisionCount={decisionStats?.total ?? null}
        autoCount={autoStats?.total ?? null}
        onJournalOpen={() => setJournalOpen(true)}
        onDecisionOpen={() => setDecisionOpen(true)}
        onAutoOpen={() => setAutoOpen(true)}
        onCarryOpen={() => setCarryOpen(true)}
        onRefresh={refresh}
      />
      <div className="research-warning" role="status">
        <AlertTriangle size={14} />
        <strong>AI ANALYSIS / MANUAL EXECUTION</strong>
        <span>
          Терминал строит карту рынка и условные сценарии. Он не размещает ордера и
          не считает качество сценария вероятностью выигрыша.
        </span>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          <AlertTriangle size={14} />
          <span>Связь с API: {error}</span>
        </div>
      )}
      <div className="workspace">
        <Watchlist markets={markets} selected={symbol} onSelect={setSymbol} />
        <section className="chart-panel panel">
          <div className="panel-toolbar">
            <div>
              <strong>{symbol}</strong>
              <span>Bybit USDT perpetual</span>
            </div>
            <div className="timeframes" aria-label="Таймфрейм">
              {(Object.keys(timeframeLabels) as Timeframe[]).map((item) => (
                <button
                  className={item === timeframe ? "active" : ""}
                  key={item}
                  onClick={() => setTimeframe(item)}
                  type="button"
                >
                  {timeframeLabels[item]}
                </button>
              ))}
            </div>
            <div className="chart-meta">
              <span>{candles.filter((item) => item.is_closed).length} свечей</span>
              <span>{analysis?.zones.length ?? 0} зон</span>
              <span className="legend ema20">EMA 20</span>
              <span className="legend ema50">EMA 50</span>
              <button
                className={`chart-density-toggle ${detailedChart ? "active" : ""}`}
                onClick={() => setDetailedChart((current) => !current)}
                type="button"
              >
                {detailedChart ? "ВСЕ СЛОИ" : "ФОКУС"}
              </button>
            </div>
          </div>
          <div className="chart-stage">
            {loadingChart && <div className="chart-loading">Загрузка свечей...</div>}
            {!loadingChart && candles.length === 0 && (
              <div className="empty-state">Нет свечных данных для {symbol}</div>
            )}
            {candles.length > 0 && (
              <PriceChart
                analysis={analysis}
                candles={candles}
                detailed={detailedChart}
                symbol={symbol}
                timeframe={timeframe}
              />
            )}
          </div>
        </section>
        <Analysis analysis={analysis} market={selectedMarket} />
      </div>
      <AiReviewPanel flow={flow} loading={aiLoading} review={aiReview} />
      <DecisionActions
        symbol={symbol}
        analysis={analysis}
        aiReview={aiReview}
        onRecorded={refreshDecisionStats}
      />
      <BottomDesk analysis={analysis} market={selectedMarket} />
      <JournalDrawer
        open={journalOpen}
        stats={journalStats}
        onClose={() => setJournalOpen(false)}
      />
      <DecisionJournalDrawer open={decisionOpen} onClose={() => setDecisionOpen(false)} />
      <AutoSignalDrawer open={autoOpen} onClose={() => setAutoOpen(false)} />
      <CarryDrawer open={carryOpen} onClose={() => setCarryOpen(false)} />
    </main>
  );
}

function Header({
  status,
  live,
  now,
  journalCount,
  decisionCount,
  autoCount,
  onJournalOpen,
  onDecisionOpen,
  onAutoOpen,
  onCarryOpen,
  onRefresh,
}: {
  status: LiveEngineStatus | null;
  live: boolean;
  now: number;
  journalCount: number | null;
  decisionCount: number | null;
  autoCount: number | null;
  onJournalOpen: () => void;
  onDecisionOpen: () => void;
  onAutoOpen: () => void;
  onCarryOpen: () => void;
  onRefresh: () => Promise<void>;
}) {
  const age = ageSeconds(status?.last_message_at ?? null);
  return (
    <header className="topbar">
      <div className="brand">
        TRADE<span>3</span>
      </div>
      <div className="exchange">
        BYBIT <span>MARKET ANALYSIS</span>
      </div>
      <div className={`live-state ${live ? "ok" : "bad"}`}>
        {live ? <Wifi size={14} /> : <WifiOff size={14} />}
        {live ? "LIVE" : (status?.state?.toUpperCase() ?? "CONNECTING")}
      </div>
      <div className="freshness">
        <Database size={13} />
        DATA {age === null ? "—" : `${age.toFixed(1)}s`}
      </div>
      <div className="topbar-spacer" />
      <button className="journal-button" onClick={onDecisionOpen} type="button">
        <ClipboardList size={13} />
        РЕШЕНИЯ <span>{decisionCount ?? 0}</span>
      </button>
      <button className="journal-button" onClick={onAutoOpen} type="button">
        <FlaskConical size={13} />
        АВТОТЕСТ <span>{autoCount ?? 0}</span>
      </button>
      <button className="journal-button" onClick={onCarryOpen} type="button">
        <Percent size={13} />
        CARRY
      </button>
      {journalCount !== null && (
        <button className="journal-button" onClick={onJournalOpen} type="button">
          <BookOpen size={13} />
          ЖУРНАЛ <span>{journalCount}</span>
        </button>
      )}
      <div className="clock">
        <Clock3 size={13} /> {moscowTime(new Date(now).toISOString())} MSK
      </div>
      <button
        className="icon-button"
        onClick={() => void onRefresh()}
        title="Обновить"
        type="button"
      >
        <RefreshCw size={15} />
      </button>
    </header>
  );
}

function Watchlist({
  markets,
  selected,
  onSelect,
}: {
  markets: Market[];
  selected: string;
  onSelect: (symbol: string) => void;
}) {
  const rankedMarkets = [...markets].sort(
    (left, right) => right.turnover_24h_usdt - left.turnover_24h_usdt,
  );
  return (
    <aside className="watchlist panel">
      <div className="section-title">
        <span>РЫНКИ И ЛИКВИДНОСТЬ</span>
        <small>TOP {markets.length || 20}</small>
      </div>
      <div className="watch-head">
        <span>#</span>
        <span>Символ</span>
        <span>24ч</span>
        <span>Funding</span>
        <span>Оборот</span>
      </div>
      <div className="watch-rows">
        {rankedMarkets.map((market, index) => (
          <button
            className={`watch-row ${selected === market.symbol ? "selected" : ""}`}
            key={market.symbol}
            onClick={() => onSelect(market.symbol)}
            type="button"
          >
            <span>{index + 1}</span>
            <span className="symbol">
              {market.base_coin}
              <small>USDT</small>
            </span>
            <span className={market.price_change_24h_pct >= 0 ? "positive" : "negative"}>
              {signed(market.price_change_24h_pct, 1)}%
            </span>
            <span>{signed(market.funding_rate_pct, 3)}%</span>
            <span>{compactUsd(market.turnover_24h_usdt)}</span>
          </button>
        ))}
        {!markets.length && <div className="list-loading">Загрузка рынков...</div>}
      </div>
      <div className="watch-footer">
        <span>Сортировка по обороту</span>
        <span>ручной выбор</span>
      </div>
    </aside>
  );
}
