import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api";
import Icon from "../components/Icon";
import LaunchCrewLogo from "../components/LaunchCrewLogo";

function Stars({ value, onChange }) {
  return (
    <div className="stars" role="radiogroup" aria-label="Rating"
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowUp") { e.preventDefault(); onChange(Math.min(5, (value || 0) + 1)); }
        if (e.key === "ArrowLeft" || e.key === "ArrowDown") { e.preventDefault(); onChange(Math.max(0, (value || 0) - 1)); }
      }}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button type="button" key={n} role="radio" aria-checked={value === n} aria-label={`${n} star${n > 1 ? "s" : ""}`}
          className={n <= value ? "star on" : "star"} onClick={() => onChange(value === n ? 0 : n)}>
          <Icon name={n <= value ? "starFilled" : "star"} size={22} />
        </button>
      ))}
    </div>
  );
}

/** Public, no-login page: a stakeholder views the preview and leaves feedback. */
export default function PublicPreview() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [html, setHtml] = useState("");
  const [err, setErr] = useState("");
  const [mode, setMode] = useState("desktop");
  const [form, setForm] = useState({ name: "", message: "", rating: 0 });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [formErr, setFormErr] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([api.publicInfo(token), api.publicHtml(token)])
      .then(([i, h]) => { if (alive) { setInfo(i); setHtml(h); } })
      .catch((e) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [token]);

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setFormErr("");
    try {
      await api.publicFeedback(token, { name: form.name.trim(), message: form.message.trim(), rating: form.rating || null });
      setSent(true);
    } catch (ex) { setFormErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <div className="public">
      <header className="public-bar"><LaunchCrewLogo size={24} /><span className="pill">Preview</span></header>
      {err && <div className="public-center"><div className="card"><h2>Link unavailable</h2><p className="muted">{err}</p></div></div>}
      {!err && !info && <div className="public-center"><div className="skeleton" style={{ height: 300, width: "min(900px,90vw)", borderRadius: 14 }} /></div>}
      {info && (
        <div className="public-grid">
          <section className="card">
            <div className="row between wrap">
              <div><h1 className="h-sm">{info.product_name}</h1><p className="muted small">You are viewing a draft. Share your thoughts on the right.</p></div>
              <div className="seg" role="group" aria-label="Viewport">
                {["desktop", "mobile"].map((m) => <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "desktop" ? "Desktop" : "Mobile"}</button>)}
              </div>
            </div>
            <div className="frame-wrap"><iframe title="Landing page preview" sandbox="allow-scripts" srcDoc={html} className={`frame ${mode}`} /></div>
          </section>
          <aside className="card">
            {sent ? (
              <div className="thanks"><div className="empty-icon"><Icon name="check" size={26} strokeWidth={1.6} /></div><h2>Thank you!</h2><p className="muted">Your feedback was sent to the page owner.</p>
                <button className="btn ghost" onClick={() => { setSent(false); setForm({ name: form.name, message: "", rating: 0 }); }}>Send more feedback</button></div>
            ) : (
              <form onSubmit={submit} className="stack">
                <h2>Your feedback</h2>
                <label>How does it feel?<Stars value={form.rating} onChange={(rating) => setForm({ ...form, rating })} /></label>
                <label>Your name (optional)<input value={form.name} maxLength={60} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
                <label>What would you change?
                  <textarea rows={5} required minLength={3} maxLength={600} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })}
                    placeholder="e.g. The headline is unclear. I did not understand what it does." /></label>
                {formErr && <div className="error" role="alert">{formErr}</div>}
                <button className="btn primary" disabled={busy || form.message.trim().length < 3}>{busy ? "Sending…" : "Send feedback"}</button>
              </form>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}