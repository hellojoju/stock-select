import { Search } from 'lucide-react';

export default function MemorySearch({ query, onChange, onSearch, results }: {
  query: string;
  onChange: (value: string) => void;
  onSearch: () => void;
  results: Array<Record<string, unknown>>;
}) {
  return (
    <>
      <div className="memory-search">
        <input value={query} onChange={(e) => onChange(e.target.value)} />
        <button onClick={onSearch}><Search size={16} /> 检索</button>
      </div>
      <div className="stack compact">
        {results.map((item, index) => (
          <p className="memory" key={index}>{String(item.content)}</p>
        ))}
      </div>
    </>
  );
}
