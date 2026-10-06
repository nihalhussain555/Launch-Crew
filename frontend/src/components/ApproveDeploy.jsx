import { useState } from "react";
import { api } from "../api";

export default function ApproveDeploy({ run, onChange }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = run.state || {};

  const approve = async () => {
    setBusy(true); setErr("");
    try { onChange(await api.approve(run.id)); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  if (run.status === "awaiting_approval") {
    const errors = s.check_summary?.errors || 0;
    return (
      <section className="card highlight">
        <h2>Ready to deploy?</h2>
        <p>Nothing is published until you approve. {errors > 0 && <strong>Heads up: {errors} check error(s) remain.</strong>}</p>
        {err && <div className="error" role="alert">{err}</div>}
        <button className="btn primary" onClick={approve} disabled={busy}>{busy ? "Starting deploy…" : "Approve & deploy"}</button>
      </section>
    );
  }
  if (run.status === "deploying") return <section className="card highlight"><h2>Deploying…</h2><p className="muted">Publishing the page and drafting your launch kit.</p></section>;
  if (run.status === "deployed")
    return (
      <section className="card highlight">
        <h2>🎉 Live</h2>
        <p><a href={s.deploy_url} target="_blank" rel="noreferrer">{s.deploy_url}</a></p>
        {s.deploy_mock && <p className="muted small">Simulated deploy — set NETLIFY_AUTH_TOKEN on the backend to publish for real.</p>}
      </section>
    );
  if (run.status === "failed") return <section className="card"><div className="error" role="alert"><strong>Run failed.</strong> {run.error}</div></section>;
  return null;
}
