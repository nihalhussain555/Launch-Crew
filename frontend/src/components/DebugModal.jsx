import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import EmptyState from "./EmptyState";
import Icon from "./Icon";
import Modal from "./Modal";

/** Autonomous debugging: re-measure the live page in a browser, then let the crew repair what it finds. */
export default function DebugModal({ open, onClose, run, onChange }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = run.state || {};
  const checks = s.check_results || [];
  const failing = checks.filter((c) => !c.passed);
  const editable = run.status === "awaiting_approval";

  const runDebug = async () => {
    setBusy(true); setErr("");
    try {
      onChange(await api.debug(run.id));
      toast("Debug pass started - watch the agent timeline.", "info");
      onClose();
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={busy ? () => {} : onClose} title="Debug the page" size="md"
      footer={<>
        <button className="btn ghost" onClick={onClose} disabled={busy}>Close</button>
        <button className="btn primary" onClick={runDebug} disabled={busy || !editable} data-autofocus>
          <Icon name="cpu" size={15} /> {busy ? "Starting…" : "Run debugger"}
        </button>
      </>}>
      <p className="muted small">
        The Critic renders the current page again at 1280px and 375px, turns every failure into fix instructions,
        routes each one to the agent that owns it and rebuilds. If the checks were already clean, nothing is rebuilt
        and no tokens are spent on fixes.
      </p>

      <div className="row wrap">
        <span className={`pill ${s.check_summary?.errors ? "err" : "ok"}`}>{s.check_summary?.errors || 0} error(s)</span>
        <span className={`pill ${s.check_summary?.warnings ? "warn" : ""}`}>{s.check_summary?.warnings || 0} warning(s)</span>
        <span className="pill">{checks.length} check(s) run</span>
        <span className="pill">review {s.iteration || 0}</span>
        <span className="pill">v{s.html_version || 0}</span>
      </div>

      {!checks.length && (
        <EmptyState icon="shield" title="No checks recorded yet" text="Browser checks run as soon as the Engineer builds the page." />
      )}
      {!!checks.length && !failing.length && (
        <p className="muted small">All checks passed on the last review - the debugger will confirm it and leave the page alone.</p>
      )}
      {!!failing.length && (
        <>
          <h3>What it will chase</h3>
          <ul className="checks">
            {failing.map((c, i) => (
              <li key={i} className={c.severity === "error" ? "err" : "warn"}>
                <span><Icon name={c.severity === "error" ? "close" : "alert"} size={17} /></span>
                <div><strong>{c.label}</strong> <span className="muted small">({c.viewport})</span>
                  {c.detail && <div className="small muted">{c.detail}</div>}</div>
              </li>
            ))}
          </ul>
        </>
      )}
      {!!s.sanitizer_violations?.length && (
        <p className="muted small">The sanitizer stripped {s.sanitizer_violations.length} unsafe item(s) from the last build; the debugger reports them again.</p>
      )}

      {err && <div className="error" role="alert">{err}</div>}
      {!editable && <p className="muted small">Debugging is available while the run awaits approval.</p>}
    </Modal>
  );
}
