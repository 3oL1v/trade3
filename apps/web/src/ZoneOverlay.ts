import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesAttachedParameter,
  Time,
  UTCTimestamp,
} from "lightweight-charts";
import type { AnalysisZone, ZoneKind } from "./types";

type Coordinates = {
  x1: number;
  x2: number;
  y1: number;
  y2: number;
  fill: string;
  stroke: string;
  label: string;
};

const palette: Record<ZoneKind, { fill: string; stroke: string; label: string }> = {
  support: { fill: "rgba(43,196,164,.09)", stroke: "rgba(43,196,164,.52)", label: "SUP" },
  resistance: { fill: "rgba(239,102,95,.09)", stroke: "rgba(239,102,95,.52)", label: "RES" },
  bullish_fvg: { fill: "rgba(79,157,249,.10)", stroke: "rgba(79,157,249,.55)", label: "FVG+" },
  bearish_fvg: { fill: "rgba(216,164,61,.10)", stroke: "rgba(216,164,61,.58)", label: "FVG-" },
  bullish_order_block: {
    fill: "rgba(117,214,180,.10)",
    stroke: "rgba(117,214,180,.6)",
    label: "OB+",
  },
  bearish_order_block: {
    fill: "rgba(245,132,125,.10)",
    stroke: "rgba(245,132,125,.6)",
    label: "OB-",
  },
  liquidity_high: {
    fill: "rgba(205,126,255,.07)",
    stroke: "rgba(205,126,255,.58)",
    label: "LIQ H",
  },
  liquidity_low: {
    fill: "rgba(205,126,255,.07)",
    stroke: "rgba(205,126,255,.58)",
    label: "LIQ L",
  },
};

class ZoneRenderer implements IPrimitivePaneRenderer {
  constructor(private readonly coordinates: () => Coordinates[]) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      context.save();
      context.font = "600 9px IBM Plex Mono, Consolas, monospace";
      for (const zone of this.coordinates()) {
        const left = Math.max(0, Math.min(zone.x1, zone.x2));
        const right = Math.min(mediaSize.width, Math.max(zone.x1, zone.x2));
        const top = Math.min(zone.y1, zone.y2);
        const height = Math.max(2, Math.abs(zone.y2 - zone.y1));
        if (right <= left || top > mediaSize.height || top + height < 0) continue;
        context.fillStyle = zone.fill;
        context.fillRect(left, top, right - left, height);
        context.strokeStyle = zone.stroke;
        context.lineWidth = 1;
        context.setLineDash([4, 3]);
        context.strokeRect(left + 0.5, top + 0.5, Math.max(0, right - left - 1), height);
        context.setLineDash([]);
        context.fillStyle = zone.stroke;
        context.fillText(zone.label, left + 5, Math.max(10, top + 11));
      }
      context.restore();
    });
  }
}

class ZonePaneView implements IPrimitivePaneView {
  constructor(private readonly primitive: ZonePrimitive) {}

  zOrder() {
    return "bottom" as const;
  }

  renderer(): IPrimitivePaneRenderer {
    return new ZoneRenderer(() => this.primitive.coordinates());
  }
}

export class ZonePrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<"Candlestick", Time> | null = null;
  private readonly view = new ZonePaneView(this);

  constructor(private readonly zones: AnalysisZone[]) {}

  attached(param: SeriesAttachedParameter<Time>): void {
    this.chart = param.chart;
    this.series = param.series as ISeriesApi<"Candlestick", Time>;
    param.requestUpdate();
  }

  detached(): void {
    this.chart = null;
    this.series = null;
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  coordinates(): Coordinates[] {
    if (!this.chart || !this.series) return [];
    const timeScale = this.chart.timeScale();
    return this.zones.flatMap((zone) => {
      const y1 = this.series?.priceToCoordinate(zone.upper);
      const y2 = this.series?.priceToCoordinate(zone.lower);
      if (y1 === null || y1 === undefined || y2 === null || y2 === undefined) return [];
      const start = toTimestamp(zone.start_time);
      const end = toTimestamp(zone.end_time);
      const x1 = timeScale.timeToCoordinate(start) ?? 0;
      const x2 = timeScale.timeToCoordinate(end);
      const colors = palette[zone.kind];
      return [
        {
          x1,
          x2: x2 ?? Number.MAX_SAFE_INTEGER,
          y1,
          y2,
          fill: colors.fill,
          stroke: colors.stroke,
          label: `${colors.label} ${zone.timeframe}`,
        },
      ];
    });
  }
}

function toTimestamp(value: string): UTCTimestamp {
  return Math.floor(Date.parse(value) / 1000) as UTCTimestamp;
}
