export function parsePacket(value: unknown): Record<string, unknown> {
  if (typeof value !== 'string') return {};
  try {
    return JSON.parse(value) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export function sourceName(value: unknown): string {
  if (!value) return '缺失';
  if (Array.isArray(value)) return value.length ? '可用' : '缺失';
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    return String(obj.source ?? obj.dataset ?? '可用');
  }
  return String(value);
}

export function labelForFactor(value: string): string {
  return { fundamental: '基本面', sector: '行业', event: '事件' }[value] ?? value;
}
