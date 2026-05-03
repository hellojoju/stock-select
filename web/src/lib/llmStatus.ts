import type { LLMStatus } from '../types';

export function llmStatusLabel(status?: LLMStatus | null): string {
  if (!status) return 'Unknown';
  if (status.state) return status.state;
  if (status.ready) return 'Ready';
  if (status.configured) return 'Error';
  return 'Off';
}

export function llmLayerImpact(status?: LLMStatus | null): string {
  if (!status) return '等待后端状态';
  if (status.last_error) return String(status.last_error);
  if (status.ready) {
    const model = status.model ? ` · ${status.model}` : '';
    return `可运行 LLM 复盘${model}`;
  }
  return '只运行确定性复盘';
}
