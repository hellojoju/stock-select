export default function ScoreBar({ label, value }: { label: string; value: number }) {
  const width = Math.max(0, Math.min(1, value)) * 100;
  return (
    <label className="score-bar">
      <span>{label}</span>
      <i><b style={{ width: `${width}%` }} /></i>
    </label>
  );
}
