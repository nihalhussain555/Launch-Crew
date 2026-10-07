/** Circular 0-100 score. Pass onClick to make it a button. */
export default function ScoreRing({ value, size = 64, stroke = 7, onClick, label }) {
  const v = Math.max(0, Math.min(100, Math.round(value ?? 0)));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const tone = v >= 85 ? "ok" : v >= 65 ? "warn" : "err";
  const svg = (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Readiness score ${v} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} className="ring-bg" strokeWidth={stroke} fill="none" />
      <circle cx={size / 2} cy={size / 2} r={r} className={`ring-fg ${tone}`} strokeWidth={stroke} fill="none"
        strokeDasharray={`${(v / 100) * c} ${c}`} strokeLinecap="round" transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" className="ring-text" style={{ fontSize: size * 0.32 }}>{v}</text>
    </svg>
  );
  return onClick ? <button className="ring-btn" onClick={onClick} title={label || "View breakdown"}>{svg}</button> : svg;
}