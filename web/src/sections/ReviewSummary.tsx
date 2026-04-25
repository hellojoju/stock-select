import { ShieldCheck } from 'lucide-react';
import Metric from '../components/Metric';

export default function ReviewSummary({ data }: { data?: Record<string, unknown> }) {
  return (
    <>
      <div className="review-summary">
        <Metric label="单笔复盘" value={Number(data?.decision_reviews ?? 0)} />
        <Metric label="盲点复盘" value={Number(data?.blindspot_reviews ?? 0)} />
        <Metric label="开放信号" value={Number(data?.open_optimization_signals ?? 0)} />
      </div>
      <p className="memory">{String(data?.system_summary ?? '暂无系统复盘')}</p>
    </>
  );
}
