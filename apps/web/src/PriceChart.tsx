import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type {
  AnalysisZone,
  Candle,
  MarketAnalysisSnapshot,
  Timeframe,
} from "./types";
import { ZonePrimitive } from "./ZoneOverlay";

interface PriceChartProps {
  analysis: MarketAnalysisSnapshot | null;
  candles: Candle[];
  detailed: boolean;
  symbol: string;
  timeframe: Timeframe;
}

const visibleZoneTimeframes: Record<Timeframe, string[]> = {
  "5": ["5", "15", "60"],
  "15": ["15", "60", "240"],
  "60": ["60", "240"],
  "240": ["240"],
};

function ema(candles: Candle[], period: number): LineData<UTCTimestamp>[] {
  if (!candles.length) return [];
  const multiplier = 2 / (period + 1);
  let current = candles[0].close;
  return candles.map((candle) => {
    current = candle.close * multiplier + current * (1 - multiplier);
    return { time: toTime(candle.start_time), value: current };
  });
}

function toTime(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

function relevantZones(
  analysis: MarketAnalysisSnapshot | null,
  timeframe: Timeframe,
  detailed: boolean,
): AnalysisZone[] {
  if (!analysis) return [];
  const allowed = visibleZoneTimeframes[timeframe];
  const ordered = analysis.zones
    .filter((zone) => allowed.includes(zone.timeframe))
    .sort((left, right) => {
      const leftDistance = Math.abs((left.lower + left.upper) / 2 - analysis.last_price);
      const rightDistance = Math.abs((right.lower + right.upper) / 2 - analysis.last_price);
      return leftDistance - rightDistance;
    });

  const selected: AnalysisZone[] = [];
  const selectedFamilies = new Set<ReturnType<typeof zoneFamily>>();
  for (const zone of ordered) {
    const family = zoneFamily(zone.kind);
    if (!detailed && selectedFamilies.has(family)) continue;

    const overlapsSelected = selected.some((candidate) => {
      if (
        detailed &&
        (candidate.kind !== zone.kind || candidate.timeframe !== zone.timeframe)
      ) {
        return false;
      }
      const overlap =
        Math.min(candidate.upper, zone.upper) - Math.max(candidate.lower, zone.lower);
      const smallerWidth = Math.min(
        candidate.upper - candidate.lower,
        zone.upper - zone.lower,
      );
      return overlap > 0 && overlap / smallerWidth >= (detailed ? 0.5 : 0.35);
    });
    if (!overlapsSelected) {
      selected.push(zone);
      selectedFamilies.add(family);
    }
    if (selected.length === (detailed ? 8 : 2)) break;
  }
  return selected;
}

function zoneFamily(kind: AnalysisZone["kind"]): "support" | "resistance" {
  return ["support", "bullish_fvg", "bullish_order_block", "liquidity_low"].includes(
    kind,
  )
    ? "support"
    : "resistance";
}

export function PriceChart({
  analysis,
  candles,
  detailed,
  symbol,
  timeframe,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0b1217" },
        textColor: "#84939e",
        fontFamily: "'IBM Plex Mono', monospace",
        fontSize: 11,
        panes: {
          separatorColor: "#25313a",
          separatorHoverColor: "#34434e",
          enableResize: false,
        },
      },
      grid: {
        vertLines: { color: "#17232b" },
        horzLines: { color: "#17232b" },
      },
      crosshair: {
        vertLine: { color: "#667680", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#667680", width: 1, style: LineStyle.Dashed },
      },
      rightPriceScale: {
        borderColor: "#26323a",
        scaleMargins: { top: 0.08, bottom: 0.2 },
      },
      timeScale: {
        borderColor: "#26323a",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 3,
        barSpacing: 7,
        tickMarkFormatter: (time: Time) => formatTime(time, false),
      },
      localization: {
        locale: "ru-RU",
        timeFormatter: (time: Time) => formatTime(time, true),
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#2bc4a4",
      downColor: "#ef665f",
      borderVisible: false,
      wickUpColor: "#2bc4a4",
      wickDownColor: "#ef665f",
      priceLineColor: "#5e7482",
    });
    const ema20 = chart.addSeries(LineSeries, {
      color: "#4f9df9",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50 = chart.addSeries(LineSeries, {
      color: "#d8a43d",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const volume = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume" },
        priceScaleId: "",
        lastValueVisible: false,
        priceLineVisible: false,
      },
      1,
    );
    chart.panes()[1]?.setHeight(105);

    const ordered = [...candles]
      .filter((item) => item.is_closed)
      .sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time));
    const candleData: CandlestickData<UTCTimestamp>[] = ordered.map((item) => ({
      time: toTime(item.start_time),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }));
    const volumeData: HistogramData<UTCTimestamp>[] = ordered.map((item) => ({
      time: toTime(item.start_time),
      value: item.volume,
      color: item.close >= item.open ? "rgba(43,196,164,.38)" : "rgba(239,102,95,.38)",
    }));
    candleSeries.setData(candleData);
    ema20.setData(ema(ordered, 20));
    ema50.setData(ema(ordered, 50));
    volume.setData(volumeData);

    const zones = relevantZones(analysis, timeframe, detailed);
    if (zones.length) {
      candleSeries.attachPrimitive(new ZonePrimitive(zones));
    }
    const structure = analysis?.structures.find((item) => item.timeframe === timeframe);
    if (structure) {
      const markers: SeriesMarker<UTCTimestamp>[] = [
        ...(detailed
          ? structure.swing_highs.slice(-8).map(
              (point): SeriesMarker<UTCTimestamp> => ({
                time: toTime(point.time),
                position: "aboveBar",
                color: "#ef827c",
                shape: "circle",
                text: "SH",
                size: 0.6,
              }),
            )
          : []),
        ...(detailed
          ? structure.swing_lows.slice(-8).map(
              (point): SeriesMarker<UTCTimestamp> => ({
                time: toTime(point.time),
                position: "belowBar",
                color: "#58d5bb",
                shape: "circle",
                text: "SL",
                size: 0.6,
              }),
            )
          : []),
        ...structure.events.slice(detailed ? -6 : -3).map(
          (event): SeriesMarker<UTCTimestamp> => ({
            time: toTime(event.time),
            position: event.kind.endsWith("up") ? "belowBar" : "aboveBar",
            color: event.kind.includes("choch") ? "#d7a7ff" : "#70aefb",
            shape: event.kind.endsWith("up") ? "arrowUp" : "arrowDown",
            text: event.kind.toUpperCase(),
          }),
        ),
      ].sort((left, right) => Number(left.time) - Number(right.time));
      createSeriesMarkers(candleSeries, markers);
    }

    const trendLines =
      analysis?.trend_lines.filter((item) => item.timeframe === timeframe) ?? [];
    for (const line of detailed ? trendLines : trendLines.slice(-2)) {
      const series = chart.addSeries(LineSeries, {
        color: line.kind === "rising_support" ? "#2bc4a4" : "#ef665f",
        lineWidth: detailed ? 2 : 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData([
        { time: toTime(line.start_time), value: line.start_price },
        { time: toTime(line.end_time), value: line.end_price },
      ]);
    }

    const preferred = analysis?.scenarios.find(
      (scenario) => scenario.direction === analysis.preferred_direction,
    );
    if (preferred) {
      const entryLines = detailed
        ? [
            {
              price: preferred.entry_zone.lower,
              color: "#4f9df9",
              title: "ENTRY",
              style: LineStyle.Dotted,
            },
            {
              price: preferred.entry_zone.upper,
              color: "#4f9df9",
              title: "",
              style: LineStyle.Dotted,
            },
          ]
        : [
            {
              price: (preferred.entry_zone.lower + preferred.entry_zone.upper) / 2,
              color: "#4f9df9",
              title: "ENTRY",
              style: LineStyle.Dotted,
            },
          ];
      const targets = detailed ? preferred.targets : preferred.targets.slice(0, 1);
      const scenarioLines = [
        ...entryLines,
        {
          price: preferred.invalidation_price,
          color: "#ef665f",
          title: "SL",
          style: LineStyle.Dashed,
        },
        ...targets.map((target) => ({
          price: target.price,
          color: "#2bc4a4",
          title: target.label,
          style: LineStyle.Dashed,
        })),
      ];
      for (const line of scenarioLines) {
        candleSeries.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth: 1,
          lineStyle: line.style,
          axisLabelVisible: Boolean(line.title),
          title: line.title,
        });
      }
    }
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [analysis, candles, detailed, symbol, timeframe]);

  return (
    <div
      className="price-chart"
      ref={containerRef}
      aria-label={`${symbol} candlestick chart with technical analysis`}
    />
  );
}

function formatTime(time: Time, includeDate: boolean): string {
  if (typeof time !== "number") return String(time);
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    day: includeDate ? "2-digit" : undefined,
    month: includeDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(time * 1000));
}
