export default function CriticReport({ state, shots }) {
  const checks = state.check_results || [];
  if (!checks.length) return null;
  const fb = state.critic_feedback;
  return (
    <section className="card">
      <h2>Critic report</h2>
      <p className="muted small">Review {state.iteration} · {state.check_summary?.errors || 0} error(s), {state.check_summary?.warnings || 0} warning(s)</p>
      <ul className="checks">
        {checks.map((c, i) => (
          <li key={i} className={c.passed ? "ok" : c.severity === "error" ? "err" : "warn"}>
            <span>{c.passed ? "✓" : c.severity === "error" ? "✕" : "!"}</span>
            <div><strong>{c.label}</strong> <span className="muted small">({c.viewport})</span>
              {c.detail && <div className="small muted">{c.detail}</div>}</div>
          </li>
        ))}
      </ul>
      {fb && (
        <>
          <h3>Fix instructions</h3>
          <p>{fb.summary}</p>
          <ul>{fb.fixes?.map((f, i) => <li key={i}><span className="pill">P{f.priority} · {f.agent}</span> {f.instruction}</li>)}</ul>
          {fb.visual_notes && <pre className="note">{fb.visual_notes}</pre>}
        </>
      )}
      {state.sanitizer_violations?.length > 0 && (
        <details><summary>Sanitizer removed {state.sanitizer_violations.length} item(s)</summary>
          <ul>{state.sanitizer_violations.map((v, i) => <li key={i} className="small">{v}</li>)}</ul></details>
      )}
      {(shots.desktop || shots.mobile) && (
        <div className="shots">
          {shots.desktop && <figure><img src={shots.desktop} alt="Desktop screenshot of the generated page" /><figcaption>Desktop 1280px</figcaption></figure>}
          {shots.mobile && <figure><img src={shots.mobile} alt="Mobile screenshot of the generated page" /><figcaption>Mobile 375px</figcaption></figure>}
        </div>
      )}
    </section>
  );
}
