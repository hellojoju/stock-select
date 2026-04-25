import ScoreBar from '../components/ScoreBar';
import { parsePacket, sourceName, labelForFactor } from '../lib/packet';
import type { Dashboard } from '../types';

export default function CandidateScores({ candidate_scores }: { candidate_scores: Dashboard['candidate_scores'] }) {
  return (
    <div className="score-list">
      {candidate_scores.slice(0, 6).map((item, index) => (
        <div className="score-card" key={`${item.strategy_gene_id}-${item.stock_code}-${index}`}>
          <div>
            <strong>{String(item.stock_code)}</strong>
            <small>{String(item.strategy_gene_id).replace('gene_', '')}</small>
          </div>
          <div className="score-bars">
            <ScoreBar label="技术" value={Number(item.technical_score)} />
            <ScoreBar label="基本面" value={Number(item.fundamental_score)} />
            <ScoreBar label="事件" value={Number(item.event_score)} />
            <ScoreBar label="行业" value={Number(item.sector_score)} />
            <ScoreBar label="风险" value={Number(item.risk_penalty)} />
          </div>
          <FactorSourceLine packet={parsePacket(item.packet_json)} />
        </div>
      ))}
    </div>
  );
}

function FactorSourceLine({ packet }: { packet: Record<string, unknown> }) {
  const sources = (packet.sources ?? {}) as Record<string, unknown>;
  const missing = (packet.missing_fields ?? []) as string[];
  const status = ['fundamental', 'sector', 'event']
    .map((key) => `${labelForFactor(key)}:${missing.includes(key) ? '缺失' : sourceName(sources[key])}`)
    .join(' · ');
  return <small className="factor-source">{status}</small>;
}
