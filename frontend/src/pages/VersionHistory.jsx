import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import RunPicker, { useRunPick } from "../components/RunPicker";
import ScoreRing from "../components/ScoreRing";
import Tabs from "../components/Tabs";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";
import { fmtDate, timeAgo } from "../utils";

/** One file row of a snapshot, with its digest so two builds can be compared by eye. */
function SnapshotFiles({ files }) {
  return (
    <ul className="file-list">
      {files.map((f) => (
        <li key={f.name} className="file-item">
          <div className="row wrap between">
            <span className="file-name mono">{f.name}</span>
            <div className="row wrap">
              <span className="muted small">{Math.max(1, Math.round(f.bytes / 1024))} KB</span>
              <span className="pill mono" title={f.hash}>{f.hash.slice(0, 10)}</span>
              {f.differs_from_live && <span className="pill warn">differs from live</span>}
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function DiffBlock({ files }) {
  return (
    <div className="stack">
      {files.map((f) => (
        <div key={f.file} className="stack">
          <p className="muted small">
            <strong className="mono">{f.file}</strong> · +{f.added} -{f.removed}{f.truncated ? " · rows truncated" : ""}
          </p>
          {!f.changed ? <p className="muted small">Identical in both states.</p> : (
            <div className="diff" role="table" aria-label={`Diff for ${f.file}`}>
              {f.rows.map((r, i) => (
                <div key={i} className={`diff-line ${r.kind}`} role="row">
                  <span className="diff-mark" aria-hidden="true">{r.kind === "add" ? "+" : r.kind === "del" ? "-" : r.kind === "hunk" ? "@" : " "}</span>
                  <span className="diff-text">{r.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** Two histories: every page build the crew published, and every whole-file-set snapshot a change took. */
export default function VersionHistory() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [tab, setTab] = useState("builds");
  const [builds, setBuilds] = useState(null);
  const [snaps, setSnaps] = useState(null);
  const [open, setOpen] = useState(null);        // { w, detail } of one workspace snapshot
  const [preview, setPreview] = useState(null);  // { v, html } of one page build
  const [pair, setPair] = useState({ w: 0, to: 0 });
  const [diff, setDiff] = useState(null);
  const [busy, setBusy] = useState("");

  const version = run?.state?.html_version || 0;
  useEffect(() => {
    setBuilds(null); setSnaps(null); setOpen(null); setPreview(null); setDiff(null); setPair({ w: 0, to: 0 });
    if (!runId) return undefined;
    let live = true;
    api.versions(runId).then((d) => live && setBuilds(d)).catch((e) => live && toast(e.message, "error"));
    api.wsVersions(runId).then((d) => live && setSnaps(d)).catch(() => {});
    return () => { live = false; };
  }, [runId, version]); // eslint-disable-line react-hooks/exhaustive-deps

  const showSnapshot = async (w) => {
    if (open?.w === w) { setOpen(null); return; }
    setBusy(`d${w}`);
    try { setOpen({ w, detail: await api.wsVersion(runId, w) }); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const compare = async (w, to) => {
    setPair({ w, to }); setDiff(null); setBusy("diff");
    try { setDiff(await api.wsDiff(runId, w, to || undefined)); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const showBuild = async (v) => {
    if (preview?.v === v) { setPreview(null); return; }
    setBusy(`p${v}`);
    try { setPreview({ v, html: await api.versionHtml(runId, v) }); }
    catch (e) { toast(e.message, "error"); setPreview(null); } finally { setBusy(""); }
  };

  const compareNearest = (v) => {
    const s = (snaps?.snapshots || []).find((x) => x.html_version === v);
    if (s) compare(s.w, 0); else toast(`No workspace snapshot was taken around v${v}.`, "info");
  };

  const restoreBuild = async (v) => {
    setBusy("restore");
    try {
      setRun(await api.restore(runId, v));
      toast(`Restoring v${v} — checks re-running`, "success");
      await refresh();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const restoreSnapshot = async (w) => {
    setBusy("restore");
    try {
      setRun(await api.wsRestore(runId, w));
      toast(`Restoring workspace w${w} — every file goes back`, "success");
      await refresh();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const tabs = [
    { id: "builds", label: "Page builds", badge: builds?.versions?.length || null },
    { id: "snapshots", label: "Workspace snapshots", badge: snaps?.snapshots?.length || null },
  ];
  const editable = run?.status === "awaiting_approval";

  return (
    <>
      <div className="page-head">
        <div><h1>Version History</h1><p className="muted">What changed, when, and how to put it back.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId} />
      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}
      {!runId && !err && <EmptyState icon="book" title="No run selected" text="Choose a run to read its history." />}

      {builds && snaps && (
        <>
          <div className="row wrap">
            <span className="pill">current page v{snaps.current_version}</span>
            <span className="pill">{builds.revisions} edit(s) this run</span>
            <span className="pill">{builds.versions.length} build(s) kept</span>
            <span className="pill">{snaps.snapshots.length}/{snaps.kept} snapshot(s)</span>
            {run?.state?.validation?.status && (
              <span className={`pill ${run.state.validation.status === "clean" ? "ok" : "err"}`}>
                last {run.state.validation.kind}: {run.state.validation.status}
              </span>
            )}
          </div>

          <Tabs tabs={tabs} active={tab} onChange={setTab} />

          {tab === "builds" && (builds.versions.length ? (
            <ul className="ver-list">
              {builds.versions.map((v) => (
                <li key={v.v} className={`ver-item ${v.current ? "current" : ""}`}>
                  <div className="ver-head">
                    <strong>v{v.v}</strong>
                    {v.current && <span className="pill ok">current</span>}
                    <span className="muted small">{fmtDate(v.at)} · {timeAgo(v.at)}</span>
                    <span className="pill">{Math.max(1, Math.round((v.bytes || 0) / 1024))} KB</span>
                    <span className={`pill ${v.errors ? "err" : "ok"}`}>{v.errors || 0} error(s)</span>
                    {v.readiness != null && <span className="pill">readiness {v.readiness}</span>}
                    {v.files?.length ? <span className="pill">{v.files.length} file(s)</span> : null}
                  </div>
                  <p className="ver-note">{v.note || "no note"}</p>
                  <div className="row wrap">
                    <button className="btn ghost small" disabled={busy === `p${v.v}`}
                      onClick={() => showBuild(v.v)} aria-expanded={preview?.v === v.v}>
                      <Icon name={preview?.v === v.v ? "eyeOff" : "eye"} size={14} /> {preview?.v === v.v ? "Hide preview" : "Preview"}
                    </button>
                    <button className="btn ghost small" disabled={!editable || busy === "restore" || v.current}
                      onClick={() => restoreBuild(v.v)}>
                      <Icon name="refresh" size={14} /> Restore this build
                    </button>
                    <button className="btn ghost small" onClick={() => { setTab("snapshots"); compareNearest(v); }}>
                      <Icon name="layers" size={14} /> Files around this build
                    </button>
                  </div>
                  {preview?.v === v.v && (
                    busy === `p${v.v}` ? <div className="skeleton" style={{ height: 200 }} />
                      : <iframe title={`Preview of version v${v.v}`} className="frame ver-frame" sandbox="allow-scripts" srcDoc={preview.html} />
                  )}
                </li>
              ))}
            </ul>
          ) : <EmptyState icon="book" title="No builds yet" text="The first snapshot lands when the Engineer publishes." />)}

          {tab === "snapshots" && (snaps.snapshots.length ? (
            <>
              <p className="muted small">A snapshot holds the whole file set as it stood before a change, so restoring one
                puts the page, its assets and its handoff note back together. The last {snaps.kept} are kept.</p>
              <ul className="ws-list">
                {snaps.snapshots.map((s) => (
                  <li key={s.w} className="ws-item">
                    <div className="row wrap between">
                      <div className="ws-main">
                        <div className="row wrap">
                          <strong>w{s.w}</strong>
                          <span className="pill">page v{s.html_version}</span>
                          <span className="muted small">{fmtDate(s.at)}</span>
                        </div>
                        <p className="muted small">{s.note}</p>
                        <div className="row wrap">
                          {(s.changed || []).map((n) => <span key={n} className="pill mono">{n}</span>)}
                        </div>
                      </div>
                      <div className="row wrap">
                        <button className="btn ghost small" onClick={() => showSnapshot(s.w)} disabled={busy === `d${s.w}`}
                          aria-expanded={open?.w === s.w}>
                          <Icon name={open?.w === s.w ? "eyeOff" : "eye"} size={14} /> {open?.w === s.w ? "Hide" : "Files"}
                        </button>
                        <button className="btn ghost small" onClick={() => compare(s.w, 0)} disabled={busy === "diff"}>
                          <Icon name="arrowRight" size={14} /> vs live
                        </button>
                        <button className="btn ghost small" disabled={!editable || busy === "restore"}
                          onClick={() => restoreSnapshot(s.w)}>
                          <Icon name="refresh" size={14} /> Restore
                        </button>
                      </div>
                    </div>
                    {open?.w === s.w && (busy === `d${s.w}`
                      ? <div className="skeleton" style={{ height: 90 }} />
                      : <SnapshotFiles files={open.detail.files} />)}
                  </li>
                ))}
              </ul>

              {snaps.snapshots.length > 1 && (
                <section className="card stack">
                  <h2>Compare two snapshots</h2>
                  <div className="row wrap diff-picks">
                    <label className="pick"><span className="muted small">Older</span>
                      <select value={pair.w} onChange={(e) => compare(Number(e.target.value), pair.to)} aria-label="Older snapshot">
                        <option value={0}>Choose…</option>
                        {snaps.snapshots.map((s) => <option key={s.w} value={s.w}>w{s.w} — {s.note || "page v" + s.html_version}</option>)}
                      </select>
                    </label>
                    <Icon name="arrowRight" size={16} />
                    <label className="pick"><span className="muted small">Newer (or live)</span>
                      <select value={pair.to} onChange={(e) => pair.w && compare(pair.w, Number(e.target.value))} aria-label="Newer snapshot">
                        <option value={0}>Live workspace</option>
                        {snaps.snapshots.map((s) => <option key={s.w} value={s.w}>w{s.w}</option>)}
                      </select>
                    </label>
                  </div>
                  {busy === "diff" && <div className="skeleton" style={{ height: 120 }} />}
                  {diff && (
                    <>
                      <p className="diff-summary">
                        <span className="pill add">+{diff.added}</span><span className="pill del">-{diff.removed}</span>
                        <span className="muted small">w{diff.from.w} ({diff.from.note || `page v${diff.from.html_version}`}) against {diff.to}.
                          {diff.changed.length ? ` ${diff.changed.join(", ")} moved.` : " Nothing moved."}</span>
                      </p>
                      <DiffBlock files={diff.files} />
                    </>
                  )}
                </section>
              )}
            </>
          ) : <EmptyState icon="layers" title="No workspace snapshots yet"
            text="A snapshot is taken the moment a change touches this run’s files — from the crew, a chat edit, an audit repair or a hand-written patch." />)}
        </>
      )}
      {run && (
        <div className="row wrap">
          {run.state?.readiness?.total != null && <ScoreRing value={run.state.readiness.total} size={44} stroke={5} />}
          <span className="muted small">Current build v{version} · {run.tokens_used.toLocaleString()} tokens spent</span>
        </div>
      )}
    </>
  );
}
