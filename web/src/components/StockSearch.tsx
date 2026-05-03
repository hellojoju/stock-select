import { useCallback, useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { request } from '../api/client';

interface StockResult {
  stock_code: string;
  name: string;
  exchange: string;
  industry: string | null;
  is_st: number | null;
  listing_status: string | null;
}

export default function StockSearch({
  onNavigate,
}: {
  onNavigate?: (stockCode: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<StockResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await request<StockResult[]>(`/api/stocks/search?q=${encodeURIComponent(q)}&limit=12`);
      setResults(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '搜索失败');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { search(query); }, 300);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [query, search]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  function handleSelect(stock: StockResult) {
    setQuery(stock.stock_code);
    setOpen(false);
    if (onNavigate) {
      onNavigate(stock.stock_code);
    } else {
      window.dispatchEvent(new CustomEvent('stock-select:navigate-stock-review', { detail: { stockCode: stock.stock_code } }));
    }
  }

  return (
    <div ref={ref} className="stock-search-box">
      <div className="stock-search-input">
        <Search size={15} />
        <input
          type="text"
          placeholder="搜索股票代码/名称"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
        {query && (
          <button className="stock-search-clear" onClick={() => { setQuery(''); setResults([]); }}>
            <X size={13} />
          </button>
        )}
      </div>

      {open && (query || results.length > 0) && (
        <div className="stock-search-popover">
          {loading && <div className="stock-search-message">搜索中...</div>}
          {error && <div className="stock-search-message danger">{error}</div>}
          {!loading && !error && results.length === 0 && query && (
            <div className="stock-search-message">未找到匹配的股票</div>
          )}
          {!loading && results.map((stock) => (
            <button
              key={stock.stock_code}
              onClick={() => handleSelect(stock)}
            >
              <b>{stock.stock_code}</b>
              <span>{stock.name}</span>
              <small>{stock.industry ?? 'unknown'}{stock.is_st ? ' · ST' : ''}{stock.listing_status && stock.listing_status !== 'active' ? ` · ${stock.listing_status}` : ''}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
