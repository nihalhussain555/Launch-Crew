import { useState } from "react";
import { api } from "../api";

const TARGETS = [
  { id: "page", label: "Layout / page" },
  { id: "copy", label: "Copy / wording" },
  { id: "design", label: "Colors / fonts" },
];

/** Shown while the run waits for approval: lets the user request a change before deploying. */
export default function ReviseForm({ run, onChange }) {
  const [text, setText] = useState("");
  const [target, setTarget] = useState("page");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  if (run.status !== "awaiting_approval") return null;
  const used = run.state?.revisions || 0;

  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { onChange(await api.revise(run.id, text.trim(), target)); setText(""); }
    catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <form className="card" onSubmit={submit}>
      <h2>Want changes first?</h2>
      <p className="muted small">Describe what to change; the crew rebuilds and re-checks the page. {used > 0 && `Changes so far: ${used}.`}</p>
      <div className="seg" role="group" aria-label="What to change">
        {TARGETS.map((t) => (
          <button type="button" key={t.id} className={target === t.id ? "on" : ""} onClick={() => setTarget(t.id)}>{t.label}</button>
        ))}
      </div>
      <textarea rows={2} required minLength={3} maxLength={500} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="e.g. Make the headline shorter and the call-to-action button larger" />
      {err && <div className="error" role="alert">{err}</div>}
      <button className="btn" disabled={busy || text.trim().length < 3}>{busy ? "Sending…" : "Apply change"}</button>
    </form>
  );
}