import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import RunPicker, { useRunPick } from "../components/RunPicker";
import Tabs from "../components/Tabs";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const blank = () => ({ file: "index.html", op: "replace", find: "", replace: "", text: "", note: "" });
const OP_HINT = {
  replace: "one exact fragment, swapped once",
  replace_all: "every occurrence of that fragment",
  append: "text added to the end of the file",
  set: "the whole new contents of the file",
};
const TONE = { error: "err", warning: "warn", info: "" };

function Risks({ risks }) {
  if (!risks?.length) return <p className="muted small">No risks found in this report.</p>;
  return (
    <ul className="risk-list">
      {risks.map((r, i) => (
        <li key={`${r.id}-${i}`} className={`risk-item ${TONE[r.severity] || ""}`}>
          <div className="row wrap">
            <Icon name={r.severity === "error" ? "close" : r.severity === "warning" ? "alert" : "help"} size={16} />
            <strong>{r.id}</strong>
            <span className={`pill ${TONE[r.severity] || ""}`}>{r.severity}</span>
          </div>
          <p className="small">{r.message}</p>
          {!!r.files?.length && <p className="muted small mono">{r.files.join(", ")}</p>}
        </li>
      ))}
    </ul>
  );
}

/** The workspace the crew publishes: indexed files, measured impact, and hand-written patches that hold. */
export default function CodeWorkspace() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [tab, setTab] = useState("files");
  const [data, setData] = useState(null);
  const [dataErr, setDataErr] = useState("");
  const [index, setIndex] = useState(null);
  const [ask, setAsk] = useState("");
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState("");
  const [changes, setChanges] = useState([blank()]);
  const [request, setRequest] = useState("");
  const [plan, setPlan] = useState(null);
  const [shown, setShown] = useState(null);

  const version = run?.state?.html_version || 0;
  useEffect(() => {
    setData(null); setDataErr(""); setIndex(null); setPlan(null); setShown(null); setReport(null);
    if (!runId) return undefined;
    let live = true;
    api.wsOverview(runId).then((d) => {
      if (!live) return;
      setData(d);
      api.wsIndex(runId).then((x) => live && setIndex(x)).catch(() => live && setIndex(null));
    }).catch((e) => live && setDataErr(e.message));
    return () => { live = false; };
  }, [runId, version]);

  const reload = async () => {
    const d = await api.wsOverview(runId).catch(() => null);
    setData(d);
    const x = await api.wsIndex(runId).catch(() => null);
    setIndex(x);
  };

  const analyse = async (e) => {
    e.preventDefault();
    const text = ask.trim();
    if (text.length < 3) return;
    setBusy("impact"); setReport(null);
    try { setReport(await api.wsImpact(runId, text)); }
    catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const patch = (i, field, value) => setChanges((list) => list.map((c, j) => (i === j ? { ...c, [field]: value } : c)));

  const makePlan = async () => {
    setBusy("plan"); setPlan(null);
    try {
      setPlan(await api.wsPlan(runId, { changes: changes.filter((c) => c.file), request: request.trim() }));
      await reload();
    } catch (ex) { setPlan({ error: ex.message }); } finally { setBusy(""); }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      setRun(await api.wsApply(runId, { changes: changes.filter((c) => c.file), request: request.trim() }));
      toast("Change queued — the page is rebuilding and re-checking", "success");
      await refresh();
      await reload();
      setPlan(null); setChanges([blank()]); setRequest("");
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const view = async (name) => {
    if (shown?.name === name) { setShown(null); return; }
    setBusy("file");
    try { setShown({ name, text: await api.fileText(runId, name) }); }
    catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const download = async () => {
    setBusy("zip");
    try {
      const url = await api.filesZip(runId);
      const a = document.createElement("a");
      a.href = url; a.download = `launch-crew-v${version}.zip`; a.click();
      URL.revokeObjectURL(url);
      toast("Workspace downloaded", "success");
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const tabs = useMemo(() => [
    { id: "files", label: "Files", badge: data?.files?.length || null },
    { id: "index", label: "Index", badge: index?.counts?.symbols || null },
    { id: "impact", label: "Impact analysis" },
    { id: "changes", label: "Changes", badge: data?.plans?.length || null },
  ], [data, index]);
  const total = (data?.files || []).reduce((n, f) => n + f.bytes, 0);
  const editable = run?.status === "awaiting_approval";

  return (
    <>
      <div className="page-head">
        <div><h1>Code Workspace</h1><p className="muted">Every file this build publishes, indexed so a change can be measured before it is made.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId}
        note="The run you pick here also drives AI Chat, Version History, Security &amp; Quality and Deployments." />

      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}
      {!runId && !err && <EmptyState icon="code" title="No run selected" text="Pick a project and run above, or launch an idea first." />}
      {dataErr && <ErrorState title="Couldn’t read the workspace" message={dataErr} retry={reload} />}
      {run && !data && !dataErr && <div className="card skeleton" style={{ height: 160 }} />}

      {data && (
        <>
          <div className="row wrap">
            <span className="pill">page v{data.version}</span>
            <span className={`pill ${working ? "warn" : ""}`}>{data.status.replace(/_/g, " ")}</span>
            <span className="pill">{data.files.length} file(s)</span>
            <span className="pill">{Math.max(1, Math.round(total / 1024))} KB</span>
            <span className="pill">{data.snapshots.length} snapshot(s)</span>
            <span className="pill">{data.revisions} edit(s) used</span>
            {data.latest_snapshot > 0 && <span className="pill">latest w{data.latest_snapshot}</span>}
          </div>

          <Tabs tabs={tabs} active={tab} onChange={setTab} />

          {tab === "files" && (data.files.length ? (
            <>
              <div className="ws-bar">
                <button className="btn ghost small" onClick={download} disabled={busy === "zip"}>
                  <Icon name="layers" size={15} /> Download all (.zip)
                </button>
                <Link className="btn ghost small" to="/versions"><Icon name="book" size={15} /> Version history</Link>
              </div>
              <ul className="file-list">
                {data.files.map((f) => (
                  <li key={f.name} className="file-item">
                    <button className="file-row" onClick={() => view(f.name)} aria-expanded={shown?.name === f.name}>
                      <Icon name="book" size={16} />
                      <span className="file-name">{f.name}</span>
                      <span className="pill">{f.language}</span>
                      <span className="muted small">{Math.max(1, Math.round(f.bytes / 1024))} KB</span>
                    </button>
                    <div className="muted small file-note">{f.note}</div>
                    {shown?.name === f.name && <pre className="file-view" aria-label={`${f.name} contents`}>{shown.text}</pre>}
                  </li>
                ))}
              </ul>
              <p className="muted small"><code className="inline-code">index.html</code> is canonical: the preview, share link,
                deploy and browser checks all read it, and <code className="inline-code">styles.css</code> /
                <code className="inline-code"> app.js</code> are rebuilt from its embedded blocks on every publish.</p>
            </>
          ) : <EmptyState icon="code" title="No files published yet" text="The workspace fills in when the Engineer builds the first version." />)}

          {tab === "index" && (index ? (
            <>
              <div className="row wrap">
                <span className="pill">measured from v{index.version}</span>
                <span className="pill">{index.counts?.symbols || 0} symbol(s)</span>
                <span className="pill">{index.counts?.refs || 0} reference(s)</span>
                <span className="pill">{index.counts?.files || data.files.length} file(s)</span>
                {index.truncated && <span className="pill warn">index truncated</span>}
              </div>
              <ul className="file-list">
                {index.files.map((f) => (
                  <li key={f.name} className="file-item">
                    <div className="row wrap between">
                      <span className="file-name">{f.name}</span>
                      <div className="row wrap">
                        <span className="pill">{f.language || "text"}</span>
                        <span className="pill">{f.symbols} declared</span>
                        <span className="pill">{f.refs} referenced</span>
                        {!f.indexed && <span className="pill warn">not indexed</span>}
                      </div>
                    </div>
                    {(f.reason || !f.indexed) && <div className="muted small file-note">{f.reason || "no symbols of this language are scanned"}</div>}
                  </li>
                ))}
              </ul>
              {!!index.names?.length && (
                <section>
                  <h3>Names this build declares</h3>
                  <div className="row wrap">{index.names.map((n) => <span key={n} className="pill mono">{n}</span>)}</div>
                </section>
              )}
            </>
          ) : <EmptyState icon="cpu" title="Nothing to index yet" text="An index needs at least one published file." />)}

          {tab === "impact" && (
            <>
              <form className="card stack" onSubmit={analyse}>
                <label>Describe a change and measure it before anything is edited
                  <input value={ask} onChange={(e) => setAsk(e.target.value)} maxLength={500}
                    placeholder="rename the #pricing anchor, restyle .btn in styles.css" aria-label="Change to analyse" />
                </label>
                <p className="muted small">Deterministic: the report comes from the workspace index, so asking costs no
                  tokens and changes nothing. {data.plans.length} plan(s) recorded so far.</p>
                <button className="btn primary" disabled={busy === "impact" || ask.trim().length < 3}>
                  <Icon name="target" size={15} /> {busy === "impact" ? "Measuring…" : "Analyse impact"}
                </button>
              </form>
              {report && (
                <section className="card stack">
                  <div className="row wrap between">
                    <h2>{report.headline}</h2>
                    <span className="pill">{report.scope}</span>
                  </div>
                  {!!report.targets?.length && (
                    <>
                      <h3>Named by the request</h3>
                      <ul className="target-list">
                        {report.targets.map((t) => (
                          <li key={`${t.kind}-${t.name}`}>
                            <div className="row wrap">
                              <strong className="mono">{t.name}</strong>
                              <span className="pill">{t.kind}</span>
                              <span className="pill">{t.op}</span>
                              {t.found ? <span className="pill ok">found</span> : <span className="pill warn">unknown</span>}
                              <span className="muted small">{t.declaration_count} declared · {t.reference_count} referenced</span>
                            </div>
                            {!!t.files?.length && <p className="muted small">{t.files.join(", ")}</p>}
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  {!!report.related_files?.length && (
                    <>
                      <h3>Files in scope</h3>
                      <ul className="related-list">
                        {report.related_files.map((f) => (
                          <li key={f.file}>
                            <div className="row wrap"><strong>{f.file}</strong><span className="pill">{f.role}</span>
                              <span className="muted small">weight {f.score}</span></div>
                            <p className="muted small">{f.why.join(" · ")}</p>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <h3>Risks</h3>
                  <Risks risks={report.risks} />
                  <details>
                    <summary className="muted small">The exact brief an agent would receive</summary>
                    <pre className="file-view">{report.block}</pre>
                  </details>
                </section>
              )}
            </>
          )}

          {tab === "changes" && (
            <>
              <section className="card stack">
                <h2>File-level change set</h2>
                <p className="muted small">Bounded patches, max {data.limits.max_changes} per change and one file each.
                  Operations: {data.limits.ops.join(", ")}. Nothing is written until you apply.</p>
                {changes.map((c, i) => (
                  <div key={i} className="change-item">
                    <div className="change-grid">
                      <label>File
                        <select value={c.file} onChange={(e) => patch(i, "file", e.target.value)} aria-label={`File ${i + 1}`}>
                          {data.files.filter((f) => f.name !== "README.md").map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
                        </select>
                      </label>
                      <label>Operation
                        <select value={c.op} onChange={(e) => patch(i, "op", e.target.value)} aria-label={`Operation ${i + 1}`}>
                          {data.limits.ops.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      </label>
                      <label>Note
                        <input value={c.note} onChange={(e) => patch(i, "note", e.target.value)} maxLength={200}
                          placeholder="why this edit" aria-label={`Note ${i + 1}`} />
                      </label>
                    </div>
                    <p className="muted small">{OP_HINT[c.op]}</p>
                    {c.op === "replace" || c.op === "replace_all" ? (
                      <>
                        <label>Text to find
                          <textarea rows={2} value={c.find} onChange={(e) => patch(i, "find", e.target.value)}
                            placeholder="an exact fragment from the file" />
                        </label>
                        <label>Replace with
                          <textarea rows={2} value={c.replace} onChange={(e) => patch(i, "replace", e.target.value)} />
                        </label>
                      </>
                    ) : (
                      <label>Text to write
                        <textarea rows={3} value={c.text} onChange={(e) => patch(i, "text", e.target.value)} />
                      </label>
                    )}
                    <div className="row wrap">
                      <button className="btn ghost small" onClick={() => setChanges((l) => (l.length > 1 ? l.filter((_, j) => j !== i) : l))}>
                        <Icon name="close" size={14} /> Remove
                      </button>
                    </div>
                  </div>
                ))}
                <div className="row wrap">
                  <button className="btn ghost small" disabled={changes.length >= data.limits.max_changes}
                    onClick={() => setChanges((l) => [...l, blank()])}><Icon name="plus" size={14} /> Add change</button>
                </div>
                <label>What you are asking for
                  <input value={request} onChange={(e) => setRequest(e.target.value)} maxLength={500}
                    placeholder="Tighten the hero copy and drop the card shadow" />
                </label>
                <div className="row wrap">
                  <button className="btn primary" onClick={makePlan} disabled={busy === "plan"}>
                    <Icon name="target" size={15} /> {busy === "plan" ? "Measuring…" : "Plan and dry-run"}
                  </button>
                  <button className="btn" onClick={apply} disabled={busy === "apply" || !editable || !plan || plan.error}>
                    <Icon name="check" size={15} /> {busy === "apply" ? "Applying…" : "Snapshot, apply and re-check"}
                  </button>
                </div>
                {!editable && <p className="muted small">Patches apply while the run awaits approval{working ? " — it is working now." : "."}</p>}
              </section>

              {plan?.error && <div className="error" role="alert">{plan.error}</div>}
              {plan && !plan.error && (
                <section className="card stack">
                  <div className="row wrap between">
                    <h2>{plan.headline}</h2>
                    <span className={`pill ${plan.safe_to_apply ? "ok" : "err"}`}>{plan.safe_to_apply ? "no blocking risks" : `${plan.impact.counts.errors} blocking risk(s)`}</span>
                  </div>
                  <ul className="projection-list">
                    {plan.projection.files.map((r) => (
                      <li key={r.file}>
                        <div className="row wrap"><strong>{r.file}</strong>
                          <span className={`pill ${r.status === "changed" ? "" : "warn"}`}>{r.status}</span>
                          <span className="pill add">+{r.lines_added}</span><span className="pill del">-{r.lines_removed}</span></div>
                      </li>
                    ))}
                  </ul>
                  {Object.entries(plan.diffs || {}).map(([name, d]) => (
                    <div key={name} className="stack">
                      <p className="muted small mono">{name} · +{d.added} -{d.removed}</p>
                      <div className="diff" role="table" aria-label={`Projected diff for ${name}`}>
                        {d.rows.map((r, i) => (
                          <div key={i} className={`diff-line ${r.kind}`} role="row">
                            <span className="diff-mark" aria-hidden="true">{r.kind === "add" ? "+" : r.kind === "del" ? "-" : r.kind === "hunk" ? "@" : " "}</span>
                            <span className="diff-text">{r.text}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                  <Risks risks={plan.impact.risks} />
                  <p className="muted small">Applying counts as one of this run’s edits ({data.revisions} used), snapshots
                    every file as w{data.latest_snapshot + 1}, rebuilds the page through the sanitizer and re-runs the
                    Chromium checks against it.</p>
                </section>
              )}

              {(data.changed_files || data.validation) && (
                <section className="card stack">
                  <h2>Last change outcome</h2>
                  {data.validation && (
                    <div className="row wrap">
                      <span className={`pill ${data.validation.status === "clean" ? "ok" : "err"}`}>{data.validation.status}</span>
                      <span className="pill">{data.validation.kind}</span>
                      <span className="pill">page v{data.validation.version}</span>
                      <span className="pill">{data.validation.check_errors} error(s)</span>
                      <span className="pill">{data.validation.check_warnings} warning(s)</span>
                      {data.validation.readiness != null && <span className="pill">readiness {data.validation.readiness}</span>}
                      {data.validation.restored_from && <span className="pill">from w{data.validation.restored_from}</span>}
                    </div>
                  )}
                  {data.changed_files && (
                    <div className="row wrap">
                      <span className="pill">{(data.changed_files.files || []).length} file(s) measured</span>
                      <span className="pill add">+{data.changed_files.lines_added}</span>
                      <span className="pill del">-{data.changed_files.lines_removed}</span>
                      {(data.changed_files.changed || []).map((n) => <span key={n} className="pill mono">{n}</span>)}
                    </div>
                  )}
                </section>
              )}

              {!!data.plans.length && (
                <section className="card stack">
                  <h2>Change plans</h2>
                  <ul className="plan-list">
                    {data.plans.map((p) => (
                      <li key={p.id} className={`plan-item ${p.status}`}>
                        <div className="row wrap between">
                          <div className="row wrap">
                            <span className={`pill ${p.status === "applied" ? "ok" : p.status === "rejected" ? "err" : ""}`}>{p.status}</span>
                            <strong>{p.request || "(no request text)"}</strong>
                          </div>
                          <span className="muted small">{timeAgo(p.at)} · measured from v{p.summary.impact_version ?? p.version}</span>
                        </div>
                        <p className="muted small">{p.summary.files.join(", ")} · scope {p.summary.scope} · {p.summary.risk_errors} error(s),
                          {p.summary.risk_warnings} warning(s){p.result?.version ? ` · applied as v${p.result.version}` : ""}
                          {p.result?.error ? ` · ${p.result.error}` : ""}</p>
                        <ul className="muted small plan-steps">
                          {p.summary.changes.map((c, i) => <li key={i} className="mono">{c.op} {c.file}{c.find ? ` — looking for ${c.find}` : ""}</li>)}
                        </ul>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
