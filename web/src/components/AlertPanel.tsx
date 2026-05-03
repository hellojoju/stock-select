import { useEffect, useRef, useState } from 'react';
import { Bell, X, TrendingUp, BarChart3, Activity } from 'lucide-react';
import { API_BASE } from '../api/client';
import type { AnnouncementEvent } from '../types';

const ALERT_TYPE_LABELS: Record<string, string> = {
  earnings_beat: '业绩大增',
  large_order: '大额订单',
  tech_breakthrough: '技术突破',
  asset_injection: '资产注入',
  m_and_a: '兼并重组',
};

export default function AlertPanel() {
  const [alerts, setAlerts] = useState<AnnouncementEvent['alert'][]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const wsUrl = API_BASE.replace('http', 'ws') + '/ws/alerts';
    let reconnectTimer: ReturnType<typeof setTimeout>;
    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        reconnectTimer = setTimeout(connect, 5000);
      };
      ws.onerror = () => setConnected(false);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'new_alert' && data.alert) {
            setAlerts((prev) => [data.alert, ...prev].slice(0, 50));
            setUnread((n) => n + 1);
          }
        } catch {
          // ignore malformed messages
        }
      };
    };

    connect();
    return () => {
      wsRef.current?.close();
      clearTimeout(reconnectTimer);
    };
  }, []);

  return (
    <div className="alert-bell-wrap">
      <button
        onClick={() => {
          setOpen(!open);
          if (open) setUnread(0);
        }}
        className="alert-bell-btn"
        title="公告报警"
      >
        <Bell size={18} className={connected ? '' : 'disconnected'} />
        {unread > 0 && (
          <span className="alert-badge">{unread > 9 ? '9+' : unread}</span>
        )}
      </button>

      {open && (
        <div className="alert-dropdown">
          <div className="alert-dropdown-header">
            <h3>实时公告报警</h3>
            <button onClick={() => { setOpen(false); setUnread(0); }} className="alert-dropdown-close">
              <X size={14} />
            </button>
          </div>

          <div className="alert-dropdown-body">
            {alerts.length === 0 ? (
              <div className="alert-dropdown-empty">
                {connected ? '暂无报警，等待新公告...' : 'WebSocket 未连接'}
              </div>
            ) : (
              alerts.map((a, i) => (
                <div key={a.alert_id + i} className={`alert-dropdown-item ${i === 0 ? 'alert-dropdown-item-new' : ''}`}>
                  <div className="alert-dropdown-indicator" style={{
                    background: a.sentiment_score >= 0.7 ? 'var(--red)' : a.sentiment_score >= 0.5 ? 'var(--amber)' : 'var(--line-strong)',
                  }} />
                  <div className="alert-dropdown-content">
                    <div className="alert-dropdown-meta">
                      <span className="alert-type-tag">{ALERT_TYPE_LABELS[a.alert_type] || a.alert_type}</span>
                      <span className="alert-stock-code">{a.stock_code}</span>
                      {a.stock_name && <span className="alert-stock-name">{a.stock_name}</span>}
                    </div>
                    <p className="alert-dropdown-title">{a.title}</p>
                    <div className="alert-dropdown-scores">
                      <span>情绪 {a.sentiment_score.toFixed(2)}</span>
                      <span className="alert-dropdown-time">{new Date(a.discovered_at).toLocaleTimeString('zh-CN')}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
