export function compactUsd(value: number): string {
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}

export function price(value: number): string {
  const digits = value >= 1000 ? 2 : value >= 1 ? 4 : 6;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(value);
}

export function signed(value: number, digits = 2): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(digits)}`;
}

export function moscowTime(value?: string | null): string {
  const date = value ? new Date(value) : new Date();
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function ageSeconds(value: string | null): number | null {
  if (!value) return null;
  return Math.max(0, (Date.now() - new Date(value).getTime()) / 1000);
}
