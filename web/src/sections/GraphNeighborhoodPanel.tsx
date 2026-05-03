import { useState } from 'react';
import { API_BASE } from '../api/client';

interface GraphNeighborhood {
  stock_code: string;
  evidence: Array<Record<string, unknown>>;
  errors: Array<Record<string, unknown>>;
  signals: Array<Record<string, unknown>>;
  documents: Array<Record<string, unknown>>;
}

export default function GraphNeighborhoodPanel() {
  const [stockCode, setStockCode] = useState('');
  const [data, setData] = useState<GraphNeighborhood | null>(null);
  const [loading, setLoading] = useState(false);

  async function search() {
    if (!stockCode) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/graph/stocks/${stockCode}/neighborhood`);
      setData(await res.json());
    } catch {
      setData(null);
    }
    setLoading(false);
  }

  return (
    <div className="graph-neighborhood">
      <div className="graph-search-row">
        <input
          value={stockCode}
          onChange={(e) => setStockCode(e.target.value)}
          placeholder="输入股票代码"
          onKeyDown={(e) => e.key === 'Enter' && search()}
        />
        <button className="btn-primary" onClick={search} disabled={!stockCode || loading}>
          查询
        </button>
      </div>

      {data && (
        <div className="graph-results">
          <section className="graph-section">
            <h4>图谱证据（{data.evidence.length}）</h4>
            {data.evidence.length === 0 ? (
              <p className="empty-value">暂无图谱证据</p>
            ) : (
              data.evidence.slice(0, 8).map((ev, i) => (
                <div className="graph-node-item" key={i}>
                  <span className="graph-node-type type-evidence">ReviewEvidence</span>
                  <span className="graph-node-label">{String(ev.props_json ?? '').slice(0, 60)}</span>
                </div>
              ))
            )}
          </section>

          <section className="graph-section">
            <h4>错误节点（{data.errors.length}）</h4>
            {data.errors.length === 0 ? (
              <p className="empty-value">暂无错误节点</p>
            ) : (
              data.errors.slice(0, 8).map((err, i) => {
                const props = parseJson(err.props_json);
                return (
                  <div className="graph-node-item" key={i}>
                    <span className="graph-node-type type-error">ReviewError</span>
                    <span className="graph-node-label">{String(props.error_type ?? err.node_id)}</span>
                    <span className="graph-node-meta">严重度 {(Number(props.severity ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                );
              })
            )}
          </section>

          <section className="graph-section">
            <h4>优化信号（{data.signals.length}）</h4>
            {data.signals.length === 0 ? (
              <p className="empty-value">暂无信号节点</p>
            ) : (
              data.signals.slice(0, 8).map((sig, i) => {
                const props = parseJson(sig.props_json);
                return (
                  <div className="graph-node-item" key={i}>
                    <span className="graph-node-type type-signal">OptimizationSignal</span>
                    <span className="graph-node-label">{String(props.signal_type ?? sig.node_id)}</span>
                    <span className="graph-node-meta">强度 {(Number(props.strength ?? 0)).toFixed(2)}</span>
                  </div>
                );
              })
            )}
          </section>

          <section className="graph-section">
            <h4>相关文档（{data.documents.length}）</h4>
            {data.documents.length === 0 ? (
              <p className="empty-value">暂无关联文档</p>
            ) : (
              data.documents.slice(0, 10).map((doc, i) => (
                <div className="graph-node-item" key={i}>
                  <span className="graph-node-type type-doc">{String(doc.source_type ?? 'doc')}</span>
                  <span className="graph-node-label">{String(doc.title ?? doc.document_id)}</span>
                </div>
              ))
            )}
          </section>
        </div>
      )}

      {!data && !loading && (
        <p className="empty-state">输入股票代码后查询图谱邻域。</p>
      )}
    </div>
  );
}

function parseJson(raw?: unknown): Record<string, unknown> {
  if (!raw) return {};
  try { return JSON.parse(String(raw)); } catch { return {}; }
}
