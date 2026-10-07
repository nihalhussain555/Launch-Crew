import Modal from "./Modal";
import ScoreRing from "./ScoreRing";

/** Explains exactly how the Launch Readiness Score was computed, and what to do next. */
export default function ReadinessModal({ open, onClose, state }) {
  const r = state?.readiness;
  if (!r) return null;
  const failed = (state.check_results || []).filter((c) => !c.passed);
  const tips = [];
  if (state.panel?.suggested_fix) tips.push(`Audience: ${state.panel.suggested_fix}`);
  failed.slice(0, 4).forEach((c) => tips.push(`${c.label}${c.detail ? ` - ${c.detail}` : ""}`));
  (state.sanitizer_violations || []).slice(0, 2).forEach((v) => tips.push(`Safety: ${v}`));

  return (
    <Modal open={open} onClose={onClose} title="Launch readiness" size="md" footer={<button className="btn ghost" onClick={onClose}>Close</button>}>
      <div className="readiness-head">
        <ScoreRing value={r.total} size={110} stroke={10} />
        <div>
          <h3>{r.verdict}</h3>
          <p className="muted">A blend of real-browser checks, a simulated audience panel and safety hygiene. No black box.</p>
        </div>
      </div>
      {r.components.map((c) => (
        <div key={c.id} className="comp">
          <div className="row between"><strong>{c.label}</strong><span>{c.score} / {c.max}</span></div>
          <div className="progress"><div className={`bar ${c.score / c.max >= 0.85 ? "ok" : c.score / c.max >= 0.6 ? "warn" : "err"}`} style={{ width: `${(c.score / c.max) * 100}%` }} /></div>
          <div className="muted small">{c.detail}</div>
        </div>
      ))}
      <h3>{tips.length ? "How to improve it" : "Nothing left to fix"}</h3>
      {tips.length > 0 && <ul className="tips">{tips.map((t, i) => <li key={i}>{t}</li>)}</ul>}
    </Modal>
  );
}