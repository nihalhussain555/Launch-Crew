import { useState } from "react";
import ConfirmModal from "../ConfirmModal";
import Icon from "../Icon";

/** The same rules the server applies, so a bad name is caught where it is typed. */
export function checkName(raw, limits) {
  const name = (raw || "").trim();
  const rules = limits?.file_names || {};
  if (!name) return "Type a file name.";
  if (rules.max_chars && name.length > rules.max_chars) return `At most ${rules.max_chars} characters.`;
  if (/[/\\]/.test(name)) return "Workspace files have no folders: one bare name.";
  if (name.includes("..")) return "“..” is not allowed in a file name.";
  if (/^[.~]/.test(name)) return "Hidden files and “~” names are not workspace files.";
  if (/\s/.test(name)) return "No spaces in a file name - use dashes.";
  if (!name.includes(".")) return "Give it an extension.";
  const ext = name.split(".").pop().toLowerCase();
  const allowed = rules.extensions || [];
  if (allowed.length && !allowed.includes(ext)) return `Only .${allowed.join(", .")} are workspace files here.`;
  if ((rules.page_names || []).includes(name)) {
    return `${name} is published from the page: open it and save, and the change goes through the patch path.`;
  }
  return "";
}

const GROUPS = [
  { id: "page", label: "Page build", test: (f) => f.kind === "page" || f.kind === "derived" },
  { id: "source", label: "Project files", test: (f) => f.kind === "source" },
  { id: "generated", label: "Generated", test: (f) => f.kind === "generated" },
];

function Row({ file, isActive, isDirty, isChanged, busy, onOpen, onStartRename, onStartDelete }) {
  return (
    <div className={`ide-row ${isActive ? "on" : ""} ${file.editable ? "" : "locked"}`}>
      <button className="ide-row-main" onClick={() => onOpen(file.name)} title={file.why}>
        <span className="ide-ext mono">{(file.name.split(".").pop() || "").slice(0, 4)}</span>
        <span className="ide-row-name">{file.name}</span>
        <span className="ide-row-flags">
          {isDirty && <span className="ide-flag dot" title="Unsaved in this tab">●</span>}
          {!isDirty && isChanged && <span className="ide-flag mod" title="Moved by the last workspace step">M</span>}
          {!file.editable && <Icon name="lock" size={12} />}
        </span>
      </button>
      <span className="ide-row-tools">
        <button className="ide-mini" onClick={() => onStartRename(file.name)} disabled={busy}
          aria-label={`Rename ${file.name}`} title="Rename"><Icon name="sliders" size={13} /></button>
        <button className="ide-mini danger" onClick={() => onStartDelete(file.name)} disabled={busy}
          aria-label={`Delete ${file.name}`} title="Delete"><Icon name="close" size={13} /></button>
      </span>
    </div>
  );
}

/**
 * The Explorer: this run's published file set exactly as `GET /workspace` lists it.
 *
 * The list is flat because the deployable is a file set, not a directory tree. Files the editor owns can
 * be created, renamed and deleted here; the page's own names open in the editor and save through the
 * patch path, which is why they carry a lock in this panel.
 */
export default function Explorer({ files, active, dirty, changed, busy, limits, onOpen, onCreate, onRename, onDelete }) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState(null);
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState("");
  const [target, setTarget] = useState("");

  const submitCreate = async (e) => {
    e.preventDefault();
    const bad = checkName(name, limits);
    if (bad) { setProblem(bad); return; }
    const ok = await onCreate(name.trim());
    if (ok === false) return setProblem("The workspace refused that name.");
    setProblem(""); setCreating(false); setName("");
  };
  const submitRename = async (e) => {
    e.preventDefault();
    const bad = checkName(draft, limits);
    if (bad) { setProblem(bad); return; }
    const ok = await onRename(renaming, draft.trim());
    if (ok === false) return setProblem("The workspace refused that name.");
    setProblem(""); setRenaming(null); setDraft("");
  };

  return (
    <div className="ide-panel ide-explorer">
      <div className="ide-panel-head">
        <strong>Explorer</strong>
        <button className="ide-mini" onClick={() => { setCreating((c) => !c); setProblem(""); }} disabled={busy}
          title="New file" aria-label="New file"><Icon name="plus" size={14} /></button>
      </div>

      {creating && (
        <form className="ide-inline-form" onSubmit={submitCreate}>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={64}
            placeholder="notes.md" aria-label="New file name" />
          <div className="row wrap">
            <button className="btn primary small" type="submit" disabled={busy}>Create</button>
            <button className="btn ghost small" type="button"
              onClick={() => { setCreating(false); setProblem(""); }}>Cancel</button>
          </div>
          {problem && <p className="ide-form-problem" role="alert">{problem}</p>}
          <p className="muted small">Allowed: .{(limits?.file_names?.extensions || []).join(", .")}</p>
        </form>
      )}

      {!files.length && <p className="muted small ide-panel-empty">Nothing published yet.</p>}
      {GROUPS.map((g) => {
        const rows = files.filter(g.test);
        if (!rows.length) return null;
        return (
          <section key={g.id} className="ide-group">
            <h4>{g.label}<span className="muted">{rows.length}</span></h4>
            {rows.map((f) => (renaming === f.name ? (
              <form key={f.name} className="ide-inline-form" onSubmit={submitRename}>
                <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={64}
                  aria-label={`New name for ${f.name}`} />
                <div className="row wrap">
                  <button className="btn primary small" type="submit" disabled={busy}>Rename</button>
                  <button className="btn ghost small" type="button"
                    onClick={() => { setRenaming(null); setProblem(""); }}>Cancel</button>
                </div>
                {problem && <p className="ide-form-problem" role="alert">{problem}</p>}
              </form>
            ) : (
              <Row key={f.name} file={f} isActive={active === f.name} isDirty={!!dirty[f.name]}
                isChanged={(changed || []).includes(f.name)} busy={busy} onOpen={onOpen}
                onStartRename={(n) => { setRenaming(n); setDraft(n); setProblem(""); setCreating(false); }}
                onStartDelete={(n) => { setTarget(n); setProblem(""); }} />
            )))}
          </section>
        );
      })}

      <p className="muted small ide-tree-note">
        One file set, no folders - the deployable is the list this run publishes.
        <code className="inline-code"> index.html</code> is canonical,<code className="inline-code"> styles.css</code> and
        <code className="inline-code"> app.js</code> are rebuilt from its blocks, and only the files you wrote here
        can be renamed or deleted.
      </p>

      <ConfirmModal open={!!target} onClose={() => setTarget("")} danger confirmLabel="Delete file"
        title="Delete this file?"
        message={target ? `${target} leaves this run's workspace. A snapshot is taken first, so undo brings it back.` : ""}
        onConfirm={async () => { if (await onDelete(target) !== false) setTarget(""); }} />
    </div>
  );
}
