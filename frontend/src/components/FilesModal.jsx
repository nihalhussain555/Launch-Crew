import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import Modal from "./Modal";

/** Multi-file workspace: the page plus the assets extracted from it, each viewable and downloadable. */
export default function FilesModal({ open, onClose, run }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [shown, setShown] = useState(null);   // { name, text } of the expanded file
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) { setData(null); setErr(""); setShown(null); return undefined; }
    setErr(""); setData(null); setShown(null);
    let live = true;
    api.files(run.id).then((d) => { if (live) setData(d); }).catch((e) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [open, run.id]);

  const toggle = async (file) => {
    if (shown && shown.name === file.name) { setShown(null); return; }
    setBusy(true);
    try { setShown({ name: file.name, text: await api.fileText(run.id, file.name) }); }
    catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  const download = async () => {
    setBusy(true);
    try {
      const url = await api.filesZip(run.id);
      const a = document.createElement("a");
      a.href = url;
      a.download = `launch-crew-v${data?.version || 1}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      toast("Workspace downloaded", "success");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  const total = (data?.files || []).reduce((n, f) => n + f.bytes, 0);

  return (
    <Modal open={open} onClose={onClose} title="Generated files" size="md"
      footer={<>
        <button className="btn ghost" onClick={onClose}>Close</button>
        <button className="btn primary" onClick={download} disabled={busy || !data?.files?.length}>
          <Icon name="layers" size={15} /> Download all (.zip)
        </button>
      </>}>
      {err && <ErrorState title="Couldn’t load the workspace" message={err} retry={() => { setData(null); setErr(""); api.files(run.id).then(setData).catch((e) => setErr(e.message)); }} />}
      {!data && !err && <div className="card skeleton" style={{ height: 120 }} />}
      {data && !data.files.length && (
        <EmptyState icon="layers" title="No files yet" text="The workspace fills in once the Engineer builds the page." />
      )}
      {data && data.files.length > 0 && (
        <>
          <p className="muted small">
            Version v{data.version} · {data.files.length} file(s) · {Math.max(1, Math.round(total / 1024))} KB total.
            <code className="inline-code">index.html</code> is self-contained, so it opens anywhere;
            the extracted assets are there for handoff.
          </p>
          <ul className="file-list">
            {data.files.map((f) => (
              <li key={f.name} className="file-item">
                <button className="file-row" onClick={() => toggle(f)} aria-expanded={!!shown && shown.name === f.name}>
                  <Icon name="book" size={16} />
                  <span className="file-name">{f.name}</span>
                  <span className="pill">{f.language}</span>
                  <span className="muted small">{Math.max(1, Math.round(f.bytes / 1024))} KB</span>
                </button>
                <div className="muted small file-note">{f.note}</div>
                {shown && shown.name === f.name && (
                  <pre className="file-view" aria-label={`${f.name} contents`}>{shown.text}</pre>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}
