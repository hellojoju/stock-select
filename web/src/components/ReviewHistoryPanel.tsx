import { useCallback, useEffect, useState } from 'react';
import { PlayCircle } from 'lucide-react';
import { API_BASE, fetchHypotheticalReviewHistory, fetchStrategyPicksHistory } from '../api/client';

export default function ReviewHistoryPanel({
  date,
  onReviewStock,
}: {
  date: string;
  onReviewStock: (code: string, reviewDate: string) => void;
}) {
  const [hypoItems, setHypoItems] = useState<Array<{ stock_code: string; trading_date: string; reviewed_at: string }>>([]);
  const [strategyItems, setStrategyItems] = useState<Array<{ stock_code: string; trading_date: string; strategy_gene_id: string; stock_name: string; industry: string }>>([]);
  const [activeSub, setActiveSub] = useState<'hypo' | 'strategy'>('hypo');
  const [loading, setLoading] = useState(false);

  const loadHistory = useCallback(() => {
    fetchHypotheticalReviewHistory(30).then((d: unknown) => {
      const data = d as { reviews?: Array<{ stock_code: string; trading_date: string; reviewed_at: string }> };
      setHypoItems(data.reviews ?? []);
    }).catch(() => setHypoItems([]));
    const loadStrategy = () => {
      fetchStrategyPicksHistory(date || undefined, 30).then((d: unknown) => {
        const data = d as { picks?: Array<{ stock_code: string; trading_date: string; strategy_gene_id: string; stock_name: string; industry: string }> };
        setStrategyItems(data.picks ?? []);
      }).catch(() => setStrategyItems([]));
    };
    loadStrategy();
  }, [date]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  async function handleRerunHypo(code: string, reviewDate: string) {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/reviews/stocks/${code}/rerun?date=${reviewDate}`, { method: 'POST' });
    } catch { /* ignore */ }
    onReviewStock(code, reviewDate);
    setLoading(false);
  }

  if (!hypoItems.length && !strategyItems.length) return null;

  return (
    <div className="review-history-panel">
      <div className="review-history-tabs">
        <button className={activeSub === 'hypo' ? 'active' : ''} onClick={() => setActiveSub('hypo')}>
          假设性复盘 ({hypoItems.length})
        </button>
        <button className={activeSub === 'strategy' ? 'active' : ''} onClick={() => setActiveSub('strategy')}>
          策略选股 ({strategyItems.length})
        </button>
      </div>

      {activeSub === 'hypo' && (
        <div className="review-history-list">
          {hypoItems.length === 0 && <p className="empty-state">暂无假设性复盘记录。输入股票代码查询后自动记录。</p>}
          {hypoItems.map((item) => (
            <div className="review-history-item clickable" key={`${item.stock_code}-${item.trading_date}`} onClick={() => onReviewStock(item.stock_code, item.trading_date)}>
              <div className="review-history-item-main">
                <strong>{item.stock_code}</strong>
                <span className="review-history-date">{item.trading_date}</span>
                <span className="review-history-time">{formatTime(item.reviewed_at)}</span>
              </div>
              <button
                className="btn-icon"
                disabled={loading}
                onClick={(e) => { e.stopPropagation(); handleRerunHypo(item.stock_code, item.trading_date); }}
                title="用最新数据重新复盘"
              >
                <PlayCircle size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {activeSub === 'strategy' && (
        <div className="review-history-list">
          {strategyItems.length === 0 && <p className="empty-state">暂无策略选股记录。</p>}
          {strategyItems.map((item, i) => (
            <button
              className="review-history-item clickable"
              key={`${item.stock_code}-${item.trading_date}-${i}`}
              onClick={() => onReviewStock(item.stock_code, item.trading_date)}
            >
              <div className="review-history-item-main">
                <strong>{item.stock_code}</strong>
                {item.stock_name && <span>{item.stock_name}</span>}
                <span className="review-history-date">{item.trading_date}</span>
                {item.industry && <span className="review-history-industry">{item.industry}</span>}
              </div>
              <span className="review-history-action-badge">{item.strategy_gene_id?.replace('gene_', '')}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function formatTime(ts: string): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  } catch {
    return ts.slice(11, 16);
  }
}
