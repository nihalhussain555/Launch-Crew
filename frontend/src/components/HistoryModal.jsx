import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import { timeAgo } from "../utils";
import ConfirmModal from "./ConfirmModal";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import Modal from "./Modal";

/** Version history: every build is snapshotted, previewable, diffable and restorable. */
export default function HistoryModal({ open, onClose, run, onChange, onDiff }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [preview, setPreview] = useState(null);   // { v, html }
  const [restore, setRestore] = useState(null);   // version awaiting confirmation
  const editable = run.status === "awaiting_approval";

  const load = () => { setErr(""); setData(null); api.versions(run.id).then(setData).catch((e) => setErr(e.message)); };
  useEffect(() => { if (!open) { setData(null); setPreview(null); setRestore(null); return; } load(); }, [open, run.id]);

  const showPreview = async (v) => {
    if (preview && preview.v === v) { setPreview(null); return; }
    try { setPreview({ v, html: await api.versionHtml(run.id, v) }); }
    catch (e) { toast(e.message, "error"); }
  };

  const doRestore = async () => {
    try { onChange(await api.restore(run.id, restore)); toast(`Restoring v${restore}…`, "info"); setRestore(null); onClose(); }
    catch (e) { toast(e.message, "error"); }
  };

  return (
    <>
      <Modal open={open} onClose={onClose} title="Version history" size="md"
        footer={<button className="btn ghost" onClick={onClose}>Close</button>}>
        {err && <ErrorState title="Couldn’t load the history" message={err} retry={load} />}
        {!data && !err && <div className="card skeleton" style={{ height: 140 }} />}
        {data && !data.versions.length && (
          <EmptyState icon="book" title="No versions yet" text="Each build is snapshotted as soon as the Engineer finishes." />
        )}
        {data && data.versions.length > 0 && (
          <>
            <p className="muted small">
              {data.versions.length} version(s) · {data.revisions} AI edit(s) so far. The page you see in the preview is v{data.current}.
            </p>
            <ul className="ver-list">
              {data.versions.map((v) => (
                <li key={v.v} className={`ver-item ${v.current ? "current" : ""}`}>
                  <div className="ver-head">
                    <strong>v{v.v}</strong>
                    {v.current && <span className="pill ok">current</span>}
                    <span className="muted small">{timeAgo(v.at)}</span>
                    <span className={`pill ${v.errors ? "err" : "ok"}`}>{v.errors ? `${v.errors} error(s)` : "checks pass"}</span>
                    {v.readiness != null && <span className="pill">{v.readiness}/100</span>}
                  </div>
                  <p className="ver-note">{v.note}</p>
                  <div className="row wrap">
                    <button className="btn ghost small" onClick={() => showPreview(v.v)} aria-expanded={!!preview && preview.v === v.v}>
                      <Icon name={preview && preview.v === v.v ? "eyeOff" : "eye"} size={14} />
                      {preview && preview.v === v.v ? "Hide preview" : "Preview"}
                    </button>
                    {!v.current && (
                      <>
                        <button className="btn ghost small" onClick={() => onDiff(v.v, data.current)}>
                          <Icon name="arrowRight" size={14} /> Compare with v{data.current}
                        </button>
                        <button className="btn ghost small" disabled={!editable} onClick={() => setRestore(v.v)}>
                          <Icon name="refresh" size={14} /> Restore this
                        </button>
                      </>
                    )}
                  </div>
                  {!editable && !v.current && <div className="muted small">Restoring is available while the run awaits approval.</div>}
                  {preview && preview.v === v.v && (
                    <iframe title={`Preview of version v${v.v}`} className="frame ver-frame"
                      sandbox="allow-scripts" srcDoc={preview.html} />
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </Modal>

      <ConfirmModal open={restore != null} onClose={() => setRestore(null)} onConfirm={doRestore}
        confirmLabel="Restore version"
        title={`Restore v${restore}?`}
        message="The crew will make this version current again and re-run the browser checks. Nothing is deleted - today's version stays in the history." />
    </>
  );
}
