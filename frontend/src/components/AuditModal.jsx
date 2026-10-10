import { useState } from "react";
import { api } from "../api";
import { AUDITS } from "../constants";
import Icon from "./Icon";
import Modal from "./Modal";
import ScoreRing from "./ScoreRing";
import EmptyState from "./EmptyState";

const TONE = { pass: "ok", warn: "warn", fail: "err", info: "" };
const FINDING_ICON = { pass: "check", warn: "alert", fail: "close", info: "help" };

/** Six deterministic scanners over the live page, and the repair loop that applies what they find. */
export default function AuditModal({ open, onClose, run, onChange }) {
  const [picked, setPicked] = useState(AUDITS.map((a) => a.kind));
  const [active, setActive] = useState("security");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = run.state || {};
  const current = s.html_version || 0;
  const editable = run.status === "awaiting_approval";
  const report = s.audits?.[active];
  const repairable = Object.entries(s.audits || {})
    .filter(([k, r]) => picked.includes(k) && r.version === current && r.fixes?.length);

  const toggle = (kind) => setPicked((p) => (p.includes(kind) ? p.filter((k) => k !== kind) : [...p, kind]));

  const call = async (fn) => {
    setBusy(true); setErr("");
    try { onChange(await fn); } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  const downloadTests = async () => {
    setBusy(true); setErr("");
    try {
      const url = URL.createObjectURL(new Blob([await api.testsFile(run.id)], { type: "text/x-python" }));
      const a = document.createElement("a");
      a.href = url; a.download = "test_page.py"; a.click();
      URL.revokeObjectURL(url);
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={busy ? () => {} : onClose} title="Crew audits" size="lg"
      footer={<>
        <button className="btn ghost" onClick={onClose} disabled={busy}>Close</button>
        <button className="btn primary" onClick={() => call(api.audit(run.id, picked))} disabled={busy || !editable || !s.html_key} data-autofocus>
          <Icon name="audit" size={15} /> {busy ? "Working…" : `Run ${picked.length} audit(s)`}
        </button>
      </>}>
      <p className="muted small">
        The crew measures the page you are looking at and stamps every report with its version, so a finding can never
        describe a build that no longer exists. Scanning calls no model and spends no tokens; applying the findings it
        finds rebuilds the page and costs one of your edits ({s.revisions || 0} used so far).
      </p>

      <div className="audit-picker" role="group" aria-label="Audits to run">
        {AUDITS.map((a) => {
          const r = s.audits?.[a.kind];
          const stale = !!r && r.version !== current;
          return (
            <span key={a.kind} className={`audit-chip ${active === a.kind ? "on" : ""}`}>
              <label className="row">
                <input type="checkbox" checked={picked.includes(a.kind)} onChange={() => toggle(a.kind)}
                  aria-label={`Include ${a.label} audit`} />
                <button className="link-btn" onClick={() => setActive(a.kind)}>
                  <Icon name={a.icon} size={15} /> {a.label}
                </button>
              </label>
              {r && <span className={`pill ${stale ? "warn" : r.errors ? "err" : r.warnings ? "warn" : "ok"}`}>
                {stale ? `v${r.version} stale` : `${r.score}/100`}
              </span>}
            </span>
          );
        })}
      </div>

      {!report ? (
        <EmptyState icon="audit" title="Not audited yet"
          text={`${AUDITS.find((a) => a.kind === active).label} has not measured this page. Tick the audits to include and run them - it takes seconds.`} />
      ) : (
        <section className="stack">
          <div className="readiness-head">
            <ScoreRing value={report.score} size={84} stroke={8} />
            <div className="stack">
              <h3>{report.label}</h3>
              <p className="muted small">{report.headline}</p>
              <div className="row wrap">
                <span className={`pill ${report.version === current ? "" : "warn"}`}>page v{report.version}</span>
                <span className={`pill ${report.errors ? "err" : "ok"}`}>{report.errors} error(s)</span>
                <span className={`pill ${report.warnings ? "warn" : ""}`}>{report.warnings} warning(s)</span>
                <span className="pill">{report.checks} check(s)</span>
                {report.kind === "tests" && <button className="btn ghost small" onClick={downloadTests} disabled={busy}>
                  <Icon name="layers" size={14} /> test_page.py
                </button>}
              </div>
            </div>
          </div>
          <p className="muted small">{AUDITS.find((a) => a.kind === active).blurb}</p>

          <ul className="checks audit-findings">
            {report.findings.map((f, i) => (
              <li key={`${f.id}-${i}`} className={TONE[f.status]}>
                <span><Icon name={FINDING_ICON[f.status] || "help"} size={17} /></span>
                <div>
                  <strong>{f.label}</strong>
                  {f.detail && <div className="small muted">{f.detail}</div>}
                  {f.fix && <div className="small finding-fix"><Icon name="arrowRight" size={12} /> {f.fix}</div>}
                </div>
              </li>
            ))}
          </ul>

          {report.version !== current ? (
            <p className="muted small">This report measured v{report.version}; the page is now v{current}. Run it again before acting on it.</p>
          ) : repairable.length ? (
            <div className="row between audit-repair">
              <span className="muted small">
                {repairable.reduce((n, [, r]) => n + r.fixes.length, 0)} instruction(s) ready across{" "}
                {repairable.map(([k]) => k).join(", ")}.
              </span>
              <button className="btn primary small" disabled={busy || !editable}
                onClick={() => call(api.auditRepair(run.id, repairable.map(([k]) => k)))}>
                <Icon name="refresh" size={14} /> Repair and re-audit
              </button>
            </div>
          ) : (
            <p className="muted small">Nothing left to repair on this build{report.errors || report.warnings ? " - the open findings are advisory." : "."}</p>
          )}
          {active === "dependency" && (
            <p className="muted small">Dependency findings are operator actions, so the crew never routes them into a page rebuild.</p>
          )}
        </section>
      )}

      {err && <div className="error" role="alert">{err}</div>}
      {!editable && <p className="muted small">Audits and repairs are available while the run awaits approval.</p>}
    </Modal>
  );
}
