export default function SeverityBadge({ value }) {
  if (!value) return <span className="muted">—</span>;
  return <span className={`badge badge-${value}`}>{value}</span>;
}