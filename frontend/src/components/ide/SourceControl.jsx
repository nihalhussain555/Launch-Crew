import { useEffect, useState } from "react";
import { api } from "../../api";
import { DiffModeToggle, FileDiffList } from "../DiffView";
import Icon from "../Icon";
import ConfirmModal from "../ConfirmModal";
import { timeAgo } from "../../utils";

/**
 * Source control over the workspace's own history: whole-file-set snapshots, the diff of any one of them
 * against the live files, a named checkpoint, undo/redo and a restore that confirms first.
 *
 * There is no Git in this deployment - no repository, no git binary and no per-run working copy - so this
 * panel says exactly that and works with the history the backend really keeps. Restoring republishes the
 * page and re-runs the checks, which is why it costs a confirmation rather than a click.
 */
export default function SourceControl({ runId, overview, dirty, onMutation, busy, setBusy }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [pick, setPick] = useState(null);          // {w, to} currently being diffed
  const [diff, setDiff] = useState(null);
  const [mode, setMode] = useState("unified");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const [labeling, setLabeling] = useState(0);
  const [labelText, setLabelText] = useState("");
  const [restore, setRestore] = useState(null);

  const load = () => { api.wsVersions(runId).then((d) => { setRows(d); setErr(""); }).catch((e) => setErr(e.message)); };
  useEffect(() => { load(); setDiff(null); setPick(null); }, [runId, overview?.latest_snapshot]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDiff = async (w, to) => {
    setBusy("diff"); setPick({ w, to }); setDiff(null);
    try { setDiff(await api.wsDiff(runId, w, to)); } catch (e) { setErr(e.message); } finally { setBusy(""); }
  };

  const checkpoint = async (e) => {
    e.preventDefault();
    setBusy("checkpoint");
    try {
      await api.wsCheckpoint(runId, label.trim(), note.trim());
      setLabel(""); setNote(""); load(); onMutation();
    } catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const step = async (dir) => {
    setBusy(dir);
    try {
      const r = dir === "undo" ? await api.wsUndo(runId, overview?.version) : await api.wsRedo(runId, overview?.version);
      onMutation(r);
    } catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const doRestore = async () => {
    setBusy("restore");
    try {
      const r = await api.wsRestore(runId, restore.w, overview?.version);
      setRestore(null); onMutation(r);
    } catch (ex) { setErr(ex.message); return false; } finally { setBusy(""); }
    return true;
  };

  const renameSnapshot = async (w) => {
    setBusy(`label${w}`);
    try { await api.wsLabel(runId, w, labelText.trim() || `checkpoint w${w}`); setLabelText(""); setLabeling(0); load(); }
    catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const undo = overview?.undo || rows?.undo || {};

  return (
    <div className="ide-panel ide-scm">
      <div className="ide-panel-head"><strong>Source Control</strong>
        <span className="muted">{rows ? `${rows.snapshots.length} snapshot(s)` : "…"}</span>
      </div>

      <div className="row wrap ide-scm-actions">
        <button className="btn ghost small" onClick={() => step("undo")} disabled={busy || !undo.can_undo}
          title={undo.next_undo != null ? `Undo to w${undo.next_undo}` : "Nothing to undo"}>
          <Icon name="undo" size={14} /> Undo{undo.undo_steps ? ` (${undo.undo_steps})` : ""}
        </button>
        <button className="btn ghost small" onClick={() => step("redo")} disabled={busy || !undo.can_redo}
          title={undo.next_redo != null ? `Redo to w${undo.next_redo}` : "Nothing to redo"}>
          <Icon name="redo" size={14} /> Redo{undo.redo_steps ? ` (${undo.redo_steps})` : ""}
        </button>
      </div>
      {!!Object.keys(dirty || {}).length && (
        <p className="ide-form-problem small">Unsaved in this tab: {Object.keys(dirty).join(", ")}. A snapshot captures
          the stored files, not the editor buffer.</p>
      )}

      <form className="ide-inline-form" onSubmit={checkpoint}>
        <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} placeholder="name this state"
          aria-label="Checkpoint label" />
        <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={160} placeholder="what it holds"
          aria-label="Checkpoint note" />
        <button className="btn primary small" type="submit" disabled={busy}>
          <Icon name="bookmark" size={14} /> Checkpoint
        </button>
      </form>
      <p className="muted small">Costs no tokens, changes no bytes, spends no revision: it keeps the whole file set as
        it is stored right now.</p>

      {err && <p className="ide-form-problem" role="alert">{err}</p>}

      <ul className="ide-scm-list">
        {(rows?.snapshots || []).map((s) => (
          <li key={s.w} className={`ide-scm-item ${pick?.w === s.w && !pick.to ? "on" : ""}`}>
            <div className="ide-scm-main">
              <button className="ide-row-main" onClick={() => openDiff(s.w, null)}>
                <span className="ide-scm-w mono">w{s.w}</span>
                <span className="ide-row-name">{s.label || s.note || "workspace snapshot"}</span>
                <span className="ide-row-flags">
                  <span className={`pill ${s.cause?.kind === "crew rebuild" ? "warn" : ""}`}>{s.cause?.kind || "unattributed"}</span>
                  <span className="muted small">{timeAgo(s.at)}</span>
                </span>
              </button>
              <span className="ide-row-tools">
                <button className="ide-mini" onClick={() => openDiff(s.w, rows.latest)} disabled={busy || s.w === rows.latest}
                  title="Compare with the newest snapshot" aria-label={`Diff w${s.w} against w${rows.latest}`}><Icon name="columns" size={13} /></button>
                <button className="ide-mini" onClick={() => setLabeling(labeling === s.w ? 0 : s.w)} disabled={busy}
                  title="Name this snapshot" aria-label={`Name w${s.w}`}><Icon name="bookmark" size={13} /></button>
                <button className="ide-mini" onClick={() => setRestore({ w: s.w, label: s.label || s.note })} disabled={busy}
                  title="Restore this file set" aria-label={`Restore w${s.w}`}><Icon name="undo" size={13} /></button>
              </span>
            </div>
            {labeling === s.w && (
              <form className="ide-inline-form" onSubmit={(e) => { e.preventDefault(); renameSnapshot(s.w); }}>
                <input autoFocus value={labelText} onChange={(e) => setLabelText(e.target.value)} maxLength={80}
                  placeholder={`name for w${s.w}`} aria-label={`Label for w${s.w}`} />
                <button className="btn primary small" type="submit" disabled={busy}>Save name</button>
              </form>
            )}
            <p className="muted small">page v{s.html_version} · {s.files.length} file(s)
              {s.changed?.length ? ` · ${s.changed.join(", ")}` : ""}</p>
          </li>
        ))}
        {rows && !rows.snapshots.length && <p className="muted small ide-panel-empty">No snapshots yet: the first change takes one.</p>}
      </ul>

      {pick && (
        <section className="ide-scm-diff">
          <div className="row wrap between">
            <h4>{diff ? `w${pick.w} → ${pick.to ? `w${pick.to}` : diff.to}` : "measuring…"}</h4>
            <DiffModeToggle mode={mode} setMode={setMode} />
          </div>
          {diff && (
            <>
              <p className="muted small">{diff.changed.length ? `${diff.changed.length} file(s) differ · ` : "no file differs · "}
                <span className="pill add">+{diff.added}</span> <span className="pill del">-{diff.removed}</span></p>
              <FileDiffList files={diff.files.filter((f) => f.changed)} mode={mode} />
            </>
          )}
        </section>
      )}

      <p className="muted small ide-tree-note">
        Git is not part of this deployment: there is no repository, no git binary and no per-run working copy,
        so branch and remote actions are not offered. Adding them needs a VCS service over the same file set
        plus a git dependency and storage for branches - the snapshots above are what history actually is here.
      </p>

      <ConfirmModal open={!!restore} onClose={() => setRestore(null)} onConfirm={doRestore} danger
        confirmLabel="Restore this file set" title={`Restore w${restore?.w || ""}?`}
        message={restore ? `“${restore.label || `w${restore.w}`}” replaces every file in this workspace, republishes the page and re-runs the browser checks. The state you are leaving is snapshotted first, so undo returns to it.` : ""} />
    </div>
  );
}
