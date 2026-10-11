import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import { DiffModeToggle, FileDiffList } from "../components/DiffView";
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

/** One checkpoint row: what it is called, what caused it, and what it can be asked to do next. */
function SnapshotRow({ s, editable, busy, openFiles, onFiles, onCompare, onRestore, onRename }) {
  const [naming, setNaming] = useState(null);      // the label being typed, or null when the row is idle
  const c = s.cause || {};
  return (
    <li className="ws-item">
      <div className="row wrap between">
        <div className="ws-main">
          <div className="row wrap">
            <strong>w{s.w}</strong>
            {s.label && <span className="pill ok"><Icon name="bookmark" size={12} /> {s.label}</span>}
            <span className="pill">page v{s.html_version}</span>
            {c.kind && <span className="pill">{c.kind}</span>}
            {c.agent && <span className="pill mono">{c.agent}</span>}
            <span className="muted small">{fmtDate(s.at)} · {timeAgo(s.at)}</span>
          </div>
          <p className="muted small">{s.note}</p>
          <div className="row wrap">
            {(s.changed || []).map((n) => <span key={n} className="pill mono">{n}</span>)}
          </div>
        </div>
        <div className="row wrap">
          <button className="btn ghost small" onClick={() => onFiles(s.w)} disabled={busy === `d${s.w}`}
            aria-expanded={openFiles}>
            <Icon name={openFiles ? "eyeOff" : "eye"} size={14} /> {openFiles ? "Hide" : "Files"}
          </button>
          <button className="btn ghost small" onClick={() => onCompare(s.w, 0)} disabled={busy === "diff"}>
            <Icon name="arrowRight" size={14} /> vs live
          </button>
          <button className="btn ghost small" onClick={() => setNaming(naming === null ? s.label : null)}>
            <Icon name="bookmark" size={14} /> {s.label ? "Rename" : "Name"}
          </button>
          <button className="btn ghost small" disabled={!editable || busy === "restore"}
            onClick={() => onRestore(s.w)}>
            <Icon name="refresh" size={14} /> Restore
          </button>
        </div>
      </div>
      {naming !== null && (
        <form className="row wrap rename" onSubmit={(e) => {
          e.preventDefault();
          const text = naming.trim();
          if (!text) return;
          onRename(s.w, text);
          setNaming(null);
        }}>
          <input value={naming} onChange={(e) => setNaming(e.target.value)} maxLength={80}
            placeholder="Name this checkpoint" aria-label={`Name for snapshot w${s.w}`} />
          <button className="btn primary small" type="submit" disabled={!naming.trim()}>Save name</button>
          <button className="btn ghost small" type="button" onClick={() => setNaming(null)}>Cancel</button>
        </form>
      )}
      {openFiles && (busy === `d${s.w}`
        ? <div className="skeleton" style={{ height: 90 }} />
        : <SnapshotFiles files={openFiles.detail.files} />)}
    </li>
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
  const [mode, setMode] = useState("unified");   // how the diff rows are read: interleaved or aligned
  const [cp, setCp] = useState({ label: "", note: "" });
  const [ask, setAsk] = useState(null);          // { kind, w } the user has to confirm before it moves
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

  const reloadSnaps = () => api.wsVersions(runId).then(setSnaps).catch(() => {});

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
      setRun(await api.wsRestore(runId, w, snaps.current_version));
      toast(`Restoring workspace w${w} — every file goes back`, "success");
      await refresh(); await reloadSnaps();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const step = async (side) => {
    setBusy("step");
    try {
      const call = side === "undo" ? api.wsUndo : api.wsRedo;
      setRun(await call(runId, snaps.current_version));
      toast(side === "undo" ? "Stepping back one change" : "Stepping forward again", "success");
      await refresh(); await reloadSnaps();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); setAsk(null); }
  };

  const saveCheckpoint = async (e) => {
    e.preventDefault();
    if (!cp.label.trim() && !cp.note.trim()) return;
    setBusy("checkpoint");
    try {
      const out = await api.wsCheckpoint(runId, cp.label.trim(), cp.note.trim());
      toast(`Checkpoint w${out.snapshot.w} kept - the page did not change`, "success");
      setCp({ label: "", note: "" });
      await reloadSnaps();
    } catch (e2) { toast(e2.message, "error"); } finally { setBusy(""); }
  };

  const renameSnapshot = async (w, label) => {
    setBusy(`n${w}`);
    try {
      await api.wsLabel(runId, w, label);
      toast(`w${w} is now named "${label}"`, "success");
      await reloadSnaps();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const tabs = [
    { id: "builds", label: "Page builds", badge: builds?.versions?.length || null },
    { id: "snapshots", label: "Workspace snapshots", badge: snaps?.snapshots?.length || null },
  ];
  const editable = run?.status === "awaiting_approval" && !working;
  const undo = snaps?.undo || {};
  const moving = ask && (
    <ConfirmModal open title={ask.kind === "undo" ? "Undo the last change?" : ask.kind === "redo" ? "Redo that change?" : "Restore this checkpoint?"}
      confirmLabel={ask.kind === "undo" ? "Undo" : ask.kind === "redo" ? "Redo" : "Restore"}
      onClose={() => setAsk(null)}
      onConfirm={() => (ask.kind === "restore" ? restoreSnapshot(ask.w) : step(ask.kind))}>
      <p className="muted small">
        {ask.kind === "restore"
          ? `Every file goes back to how it was at w${ask.w}. Nothing is deleted: the state you are leaving is snapshotted first, so this too can be undone.`
          : `The crew re-checks the page afterwards, which takes a moment. The run keeps its history: this step is itself one more entry, and one undo away.`}
      </p>
    </ConfirmModal>
  );

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

          {tab === "snapshots" && (
            <div className="row wrap vc-bar">
              <div className="row wrap">
                <button className="btn ghost small" disabled={!undo.can_undo || !editable || busy === "step"}
                  onClick={() => setAsk({ kind: "undo" })} title={undo.can_undo ? `Back to w${undo.next_undo}` : "Nothing recorded yet"}>
                  <Icon name="undo" size={14} /> Undo{undo.undo_steps ? ` (${undo.undo_steps})` : ""}
                </button>
                <button className="btn ghost small" disabled={!undo.can_redo || !editable || busy === "step"}
                  onClick={() => setAsk({ kind: "redo" })} title={undo.can_redo ? `Forward to w${undo.next_redo}` : "Nothing has been stepped back"}>
                  <Icon name="redo" size={14} /> Redo{undo.redo_steps ? ` (${undo.redo_steps})` : ""}
                </button>
                <span className="muted small">
                  {undo.can_undo || undo.can_redo
                    ? `${undo.undo_steps} step(s) back, ${undo.redo_steps} forward. Each step keeps the state it leaves.`
                    : "Undo and redo follow the checkpoints: every change the crew or you makes is recorded before it lands."}
                </span>
              </div>
              <form className="row wrap cp-form" onSubmit={saveCheckpoint}>
                <input value={cp.label} onChange={(e) => setCp({ ...cp, label: e.target.value })} maxLength={80}
                  placeholder="Name this state" aria-label="Checkpoint name" />
                <input value={cp.note} onChange={(e) => setCp({ ...cp, note: e.target.value })} maxLength={200}
                  placeholder="What it is (optional)" aria-label="Checkpoint description" />
                <button className="btn secondary small" type="submit"
                  disabled={busy === "checkpoint" || !editable || (!cp.label.trim() && !cp.note.trim())}>
                  <Icon name="bookmark" size={14} /> {busy === "checkpoint" ? "Keeping…" : "Checkpoint"}
                </button>
              </form>
            </div>
          )}

          {tab === "snapshots" && (snaps.snapshots.length ? (
            <>
              <p className="muted small">A snapshot holds the whole file set as it stood before a change, so restoring one
                puts the page, its assets and its handoff note back together. The last {snaps.kept} are kept; a checkpoint
                you name is added to this list without changing a byte of the page.</p>
              <ul className="ws-list">
                {snaps.snapshots.map((s) => (
                  <SnapshotRow key={s.w} s={s} editable={editable} busy={busy}
                    openFiles={open?.w === s.w ? open : null}
                    onFiles={showSnapshot} onCompare={compare}
                    onRestore={(w) => setAsk({ kind: "restore", w })} onRename={renameSnapshot} />
                ))}
              </ul>

              {snaps.snapshots.length > 1 && (
                <section className="card stack">
                  <div className="row wrap between">
                    <h2>Compare two snapshots</h2>
                    <DiffModeToggle mode={mode} setMode={setMode} />
                  </div>
                  <div className="row wrap diff-picks">
                    <label className="pick"><span className="muted small">Older</span>
                      <select value={pair.w} onChange={(e) => compare(Number(e.target.value), pair.to)} aria-label="Older snapshot">
                        <option value={0}>Choose…</option>
                        {snaps.snapshots.map((s) => <option key={s.w} value={s.w}>w{s.w} — {s.label || s.note || "page v" + s.html_version}</option>)}
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
                        <span className="muted small">w{diff.from.w} ({diff.from.label || diff.from.note || `page v${diff.from.html_version}`}) against {diff.to}.
                          {diff.changed.length ? ` ${diff.changed.join(", ")} moved.` : " Nothing moved."}
                          {mode === "side" ? " Unchanged stretches are folded; the two columns are the same pair of files." : ""}</span>
                      </p>
                      <FileDiffList files={diff.files} mode={mode} />
                    </>
                  )}
                </section>
              )}
            </>
          ) : <EmptyState icon="layers" title="No workspace snapshots yet"
            text="A snapshot is taken the moment a change touches this run’s files — from the crew, a chat edit, an audit repair or a hand-written patch." />)}
        </>
      )}
      {moving}
      {run && (
        <div className="row wrap">
          {run.state?.readiness?.total != null && <ScoreRing value={run.state.readiness.total} size={44} stroke={5} />}
          <span className="muted small">Current build v{version} · {run.tokens_used.toLocaleString()} tokens spent</span>
        </div>
      )}
    </>
  );
}
