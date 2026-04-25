export function formatPct(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  return `${(value * 100).toFixed(2)}%`;
}

export function formatAmount(value?: number): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '-';
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(1)} 亿`;
  return `${value.toFixed(0)}`;
}
