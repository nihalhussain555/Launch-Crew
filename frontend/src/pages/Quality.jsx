import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import CriticReport from "../components/CriticReport";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import RunPicker, { useRunPick } from "../components/RunPicker";
import ScoreRing from "../components/ScoreRing";
import StatusPill from "../components/StatusPill";
import Tabs from "../components/Tabs";
import { AUDITS } from "../constants";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const TONE = { pass: "ok", warn: "warn", fail: "err", info: "" };
const FINDING_ICON = { pass: "check", warn: "alert", fail: "close", info: "help" };
const KIND_OF = Object.fromEntries(AUDITS.map((a) => [a.kind, a]));

function Findings({ findings }) {
  return (
    <ul className="checks audit-findings">
      {findings.map((f, i) => (
        <li key={`${f.id}-${i}`} className={TONE[f.status] || ""}>
          <span><Icon name={FINDING_ICON[f.status] || "help"} size={17} /></span>
          <div>
            <strong>{f.label}</strong>
            {f.detail && <div className="small muted">{f.detail}</div>}
            {f.fix && <div className="small finding-fix"><Icon name="arrowRight" size={12} /> {f.fix}</div>}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** One audit report card: the score it measured, what it found, and whether its findings are repairable now. */
function AuditCard({ report, current, onPick, picked, onRun }) {
  const meta = KIND_OF[report.kind] || {};
  const stale = report.version !== current;
  return (
    <section className={`card stack audit-card ${stale ? "stale" : ""}`}>
      <div className="row wrap between">
        <div className="row wrap">
          <label className="row audit-pick">
            <input type="checkbox" checked={picked} onChange={onPick} aria-label={`Include ${meta.label || report.kind} audit`} />
            <span className="stat-icon"><Icon name={meta.icon || "audit"} size={18} /></span>
          </label>
          <div>
            <h2>{report.label}</h2>
            <p className="muted small">{report.headline}</p>
          </div>
        </div>
        <ScoreRing value={report.score} size={62} stroke={6} />
      </div>
      <div className="row wrap">
        <span className={`pill ${stale ? "warn" : ""}`}>measured v{report.version}{stale ? " · stale" : " · current"}</span>
        <span className={`pill ${report.errors ? "err" : "ok"}`}>{report.errors} error(s)</span>
        <span className={`pill ${report.warnings ? "warn" : ""}`}>{report.warnings} warning(s)</span>
        <span className="pill">{report.checks} check(s)</span>
        {!!report.fixes?.length && <span className="pill">{report.fixes.length} instruction(s) ready</span>}
        <button className="btn ghost small" onClick={onRun} disabled={stale}>
          <Icon name="refresh" size={14} /> Re-run
        </button>
      </div>
      {stale
        ? <p className="muted small">This report measured v{report.version}; the page is now v{current}.
          Its findings describe markup that no longer exists, so run it again before acting.</p>
        : <p className="muted small">{meta.blurb}</p>}
      <Findings findings={report.findings} />
    </section>
  );
}

/** The crew's deterministic scanners over the live page, plus the repair loop that applies their findings. */
export default function Quality() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [tab, setTab] = useState("audits");
  const [picked, setPicked] = useState(AUDITS.map((a) => a.kind));
  const [tests, setTests] = useState(null);
  const [busy, setBusy] = useState("");
  const [shots, setShots] = useState({});

  const s = run?.state || {};
  const current = s.html_version || 0;
  const audits = Object.values(s.audits || {});
  const editable = run?.status === "awaiting_approval";
  const repairable = Object.entries(s.audits || {})
    .filter(([k, r]) => r.version === current && r.fixes?.length && picked.includes(k));
  const openErrors = audits.filter((r) => r.version === current).reduce((n, r) => n + (r.errors || 0), 0);

  useEffect(() => { setTests(null); setShots({}); }, [runId]);
  useEffect(() => {
    if (tab !== "tests" || !runId) return;
    api.tests(runId).then(setTests).catch((e) => setTests({ error: e.message || "The test suite could not be read." }));
  }, [tab, runId, s.html_version]);

  const shotKeys = s.screenshot_keys || {};
  const shotTag = Object.keys(shotKeys).join(",");
  useEffect(() => {
    if (!shotTag) return;
    ["desktop", "mobile"].filter((vp) => shotKeys[vp]).forEach((vp) =>
      api.screenshotUrl(runId, vp).then((u) => setShots((p) => { if (p[vp]) URL.revokeObjectURL(p[vp]); return { ...p, [vp]: u }; })).catch(() => {}));
  }, [shotTag, runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const call = async (fn, done) => {
    setBusy("work");
    try { setRun(await fn); toast(done, "success"); await refresh(); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const runAudits = (kinds) => call(api.audit(runId, kinds), `${kinds.length} audit(s) measured against v${current}`);
  const repair = () => call(api.auditRepair(runId, repairable.map(([k]) => k)),
    `Applying ${repairable.reduce((n, [, r]) => n + r.fixes.length, 0)} instruction(s) and re-auditing`);

  const downloadTests = async () => {
    setBusy("dl");
    try {
      const url = URL.createObjectURL(new Blob([await api.testsFile(runId)], { type: "text/x-python" }));
      const a = document.createElement("a"); a.href = url; a.download = "test_page.py"; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const toggle = (kind) => setPicked((p) => (p.includes(kind) ? p.filter((k) => k !== kind) : [...p, kind]));

  const tabs = [
    { id: "audits", label: "Crew audits", badge: audits.length || null, tone: openErrors ? "err" : "" },
    { id: "browser", label: "Browser checks" },
    { id: "tests", label: "Regression tests" },
    { id: "changes", label: "Change safety" },
  ];

  return (
    <>
      <div className="page-head">
        <div><h1>Security &amp; Quality</h1><p className="muted">Six scanners measure the page that is live right now.
          They call no model, so reading costs nothing and changes nothing.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId} />

      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}
      {!runId && !err && <EmptyState icon="shield" title="No run selected" text="Choose a run to measure its page." />}

      {run && (
        <>
          <div className="row wrap">
            <StatusPill status={run.status} />
            <span className="pill">page v{current}</span>
            <span className="pill">{audits.length} report(s)</span>
            <span className={`pill ${openErrors ? "err" : "ok"}`}>{openErrors} audit error(s) on this build</span>
            <span className={`pill ${(s.check_summary?.errors || 0) ? "err" : "ok"}`}>{s.check_summary?.errors || 0} check error(s)</span>
            {s.sanitizer_violations?.length ? <span className="pill warn">sanitizer stripped {s.sanitizer_violations.length}</span> : null}
          </div>

          <div className="ws-bar">
            <button className="btn primary small" disabled={busy === "work" || !editable || !s.html_key || !picked.length}
              onClick={() => runAudits(picked)}>
              <Icon name="audit" size={15} /> {busy === "work" ? "Working…" : `Run ${picked.length} audit(s)`}
            </button>
            <button className="btn ghost small" disabled={!repairable.length || busy === "work" || !editable} onClick={repair}>
              <Icon name="refresh" size={15} /> Repair and re-audit
            </button>
          </div>

          <div className="audit-picker">
            {AUDITS.map((a) => {
              const r = s.audits?.[a.kind];
              return (
                <span key={a.kind} className={`audit-chip ${picked.includes(a.kind) ? "on" : ""}`}>
                  <label className="row">
                    <input type="checkbox" checked={picked.includes(a.kind)} onChange={() => toggle(a.kind)}
                      aria-label={`Include ${a.label} audit`} />
                    <Icon name={a.icon} size={15} /> {a.label}
                  </label>
                  {r && <span className={`pill ${r.version !== current ? "warn" : r.errors ? "err" : r.warnings ? "warn" : "ok"}`}>
                    {r.version !== current ? `v${r.version} stale` : `${r.score}/100`}
                  </span>}
                </span>
              );
            })}
          </div>

          {!editable && <p className="muted small">Audits and repairs are available while the run awaits approval.</p>}

          <Tabs tabs={tabs} active={tab} onChange={setTab} />

          {tab === "audits" && (audits.length ? (
            <div className="stack">
              {AUDITS.filter((a) => s.audits?.[a.kind]).map((a) => (
                <AuditCard key={a.kind} report={s.audits[a.kind]} current={current}
                  picked={picked.includes(a.kind)} onPick={() => toggle(a.kind)} onRun={() => runAudits([a.kind])} />
              ))}
            </div>
          ) : <EmptyState icon="audit" title="Nothing audited yet"
            text="Tick the scanners above and run them - they read the page and the workspace files, and stamp every report with the version it measured." />)}

          {tab === "browser" && (s.check_results?.length ? (
            <div className="stack">
              <CriticReport state={s} shots={shots} />
              <p className="muted small">Screenshots are written by the Critic on each review, so they always show the
                build being measured. Desktop 1280px and mobile 375px.</p>
            </div>
          ) : <EmptyState icon="monitor" title="No browser checks recorded"
            text="The Critic reviews the page in real Chromium once the Engineer publishes a build." />)}

          {tab === "tests" && (!tests ? <div className="card skeleton" style={{ height: 140 }} /> : tests.error ? (
            <EmptyState icon="check" title="No suite yet" text={tests.error} />
          ) : (
            <section className="card stack">
              <div className="row wrap between">
                <h2>tests/test_page.py</h2>
                <div className="row wrap">
                  <span className={`pill ${tests.ran ? (tests.failed ? "err" : "ok") : "warn"}`}>
                    {!tests.ran ? "did not run" : tests.failed ? `${tests.failed} failing` : "all passing"}</span>
                  <span className="pill">{(tests.cases || []).length} case(s)</span>
                  <span className="pill ok">{tests.passed} passed</span>
                  {!!tests.failed && <span className="pill err">{tests.failed} failed</span>}
                  <span className={`pill ${tests.version === current ? "" : "warn"}`}>page v{tests.version}</span>
                  <button className="btn ghost small" onClick={downloadTests} disabled={busy === "dl"}>
                    <Icon name="layers" size={14} /> Download
                  </button>
                </div>
              </div>
              <p className="muted small">Written from the page that was live, then executed here in a throwaway directory
                with this service's own interpreter - standard library only.
                {tests.generated_at ? ` Generated ${timeAgo(tests.generated_at)}.` : ""}
                {tests.reason ? ` ${tests.reason}` : ""}</p>
              {!!(tests.cases || []).filter((c) => !c.ok).length && (
                <>
                  <h3>Cases that no longer hold</h3>
                  <ul className="checks">
                    {tests.cases.filter((c) => !c.ok).map((c, i) => (
                      <li key={i} className="err"><span><Icon name="close" size={17} /></span>
                        <div><strong>{c.name}</strong><div className="small muted">{c.detail}</div></div></li>
                    ))}
                  </ul>
                </>
              )}
              {!!(tests.cases || []).length && (
                <>
                  <h3>Every case in the suite</h3>
                  <ul className="tips">
                    {tests.cases.map((c, i) => (
                      <li key={i} className="small"><span className={`pill ${c.ok ? "ok" : "err"}`}>{c.ok ? "pass" : "fail"}</span> {c.name}</li>
                    ))}
                  </ul>
                </>
              )}
              {tests.output && (
                <details><summary className="muted small">Raw interpreter output</summary>
                  <pre className="file-view">{tests.output}</pre></details>
              )}
            </section>
          ))}

          {tab === "changes" && (
            <div className="stack">
              <section className="card stack">
                <h2>Impact of the last measured change</h2>
                {s.impact ? (
                  <>
                    <div className="row wrap">
                      <span className="pill">measured from v{s.impact.version}</span>
                      <span className="pill">{s.impact.scope}</span>
                      <span className={`pill ${s.impact.counts?.errors ? "err" : "ok"}`}>{s.impact.counts?.errors || 0} blocking risk(s)</span>
                      <span className="pill">{s.impact.counts?.warnings || 0} warning(s)</span>
                      <span className="pill">{(s.impact.targets || []).length} name(s)</span>
                      <span className="pill">{(s.impact.related_files || []).length} file(s) in scope</span>
                    </div>
                    <p className="muted small">{s.impact.request}</p>
                    {!!s.impact.risks?.length && <Findings findings={s.impact.risks.map((r) => ({
                      id: r.id, status: r.severity === "error" ? "fail" : r.severity === "warning" ? "warn" : "info",
                      label: r.id, detail: r.message, fix: r.files?.length ? r.files.join(", ") : "" }))} />}
                  </>
                ) : <p className="muted small">No impact report has been measured for this run yet. It is produced
                  automatically before every crew edit, and on demand from
                  {" "}<Link to="/workspace">Code Workspace</Link>.</p>}
              </section>

              <section className="card stack">
                <h2>How the last change fared</h2>
                {s.validation ? (
                  <div className="row wrap">
                    <span className={`pill ${s.validation.status === "clean" ? "ok" : s.validation.status === "pending" ? "warn" : "err"}`}>{s.validation.status}</span>
                    <span className="pill">{s.validation.kind}</span>
                    <span className="pill">page v{s.validation.version}</span>
                    <span className="pill">{s.validation.check_errors || 0} error(s)</span>
                    <span className="pill">{s.validation.check_warnings || 0} warning(s)</span>
                    {s.validation.readiness != null && <span className="pill">readiness {s.validation.readiness}</span>}
                    {s.validation.sanitizer_removed ? <span className="pill warn">{s.validation.sanitizer_removed} stripped by sanitizer</span> : null}
                    {s.validation.restored_from && <span className="pill">restored from w{s.validation.restored_from}</span>}
                  </div>
                ) : <p className="muted small">Nothing has been changed on this run since its first build.</p>}
                {s.changed_files && (
                  <div className="row wrap">
                    <span className="pill add">+{s.changed_files.lines_added}</span>
                    <span className="pill del">-{s.changed_files.lines_removed}</span>
                    {(s.changed_files.changed || []).map((n) => <span key={n} className="pill mono">{n}</span>)}
                  </div>
                )}
                <p className="muted small">A hand-written patch gets no free pass: the rebuilt page goes through the
                  same sanitizer, Chromium checks and readiness score as a generated one.
                  {" "}<Link to="/versions">Version History</Link> can put any of it back.</p>
              </section>

              {!!s.style?.label && (
                <section className="card stack">
                  <h2>Design direction under test</h2>
                  <div className="row wrap">
                    <span className="pill">{s.style.label}</span>
                    <span className="pill">{s.style.layout_style}</span>
                    <span className="pill">{s.style.hero}</span>
                    <span className="pill">{s.style.motif}</span>
                    <span className="pill">{s.style.radius}</span>
                  </div>
                  <p className="muted small">{s.style.hero_note}</p>
                  {!!s.style.order?.length && <p className="muted small">Sections: {s.style.order.join(" → ")}</p>}
                  <div className="row wrap">
                    {Object.entries(s.style.palette || {}).map(([role, value]) => (
                      <span key={role} className="pill"><i className="swatch" style={{ background: String(value) }} aria-hidden="true" /> {role}</span>
                    ))}
                  </div>
                  <p className="muted small">One direction is seeded per run and reused by every later edit, so a
                    revision cannot quietly restyle the page into a different product.</p>
                </section>
              )}
            </div>
          )}
        </>
      )}
    </>
  );
}
