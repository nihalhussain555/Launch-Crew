import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import AssistantPanel from "../components/ide/AssistantPanel";
import BottomPanel from "../components/ide/BottomPanel";
import Explorer from "../components/ide/Explorer";
import LivePreview from "../components/LivePreview";
import MonacoEditor from "../components/ide/MonacoEditor";
import SearchPanel from "../components/ide/SearchPanel";
import SourceControl from "../components/ide/SourceControl";
import Icon from "../components/Icon";
import StatusPill from "../components/StatusPill";
import ConfirmModal from "../components/ConfirmModal";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import { useRun } from "../hooks/useRun";
import { useRunStream } from "../hooks/useRunStream";
import { useTheme } from "../theme";
import { useToast } from "../toast";

const VIEWS = [
  { id: "explorer", label: "Explorer", icon: "folder" },
  { id: "search", label: "Search", icon: "search" },
  { id: "scm", label: "Source Control", icon: "layers" },
  { id: "settings", label: "IDE settings", icon: "gear" },
];
const PREFS_KEY = "lc_ide_prefs";
const DEFAULT_PREFS = { fontSize: 13.5, wordWrap: false, minimap: false, tabSize: 2 };

const readPrefs = () => {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; }
  catch { return DEFAULT_PREFS; }
};

/**
 * The browser IDE over a run's real workspace.
 *
 * One rule shapes everything here: a tab is a stored file, and a save is an authenticated API call that
 * either writes that file (source files) or asks the pipeline to rebuild the page from it
 * (index.html/styles.css/app.js). No buffer is ever the only copy, and nothing in this shell pretends to
 * have run, built or tested something - the panels say what the backend actually reported.
 */
export default function Ide() {
  const { runId } = useParams();
  const toast = useToast();
  const { theme } = useTheme();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const { events, connected } = useRunStream(runId);
  const editor = useRef(null);

  const [overview, setOverview] = useState(null);
  const [dataErr, setDataErr] = useState("");
  const [view, setView] = useState("explorer");
  const [docs, setDocs] = useState({});              // name -> the file as stored, plus its digest
  const [tabs, setTabs] = useState([]);              // open file names, in order
  const [active, setActive] = useState("");
  const [dirty, setDirty] = useState({});
  const [markers, setMarkers] = useState({});
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const [busy, setBusy] = useState("");
  const [discard, setDiscard] = useState("");
  const [showBottom, setShowBottom] = useState(true);
  const [sideOpen, setSideOpen] = useState(true);
  const [preview, setPreview] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [pendingJump, setPendingJump] = useState(null);
  const [prefs, setPrefs] = useState(readPrefs);

  const version = run?.state?.html_version ?? overview?.version ?? 0;
  const editable = run?.status === "awaiting_approval";
  const tabsRef = useRef([]);
  tabsRef.current = tabs;

  const load = useCallback(async () => {
    try {
      const d = await api.wsOverview(runId);
      setOverview(d); setDataErr("");
      setDocs((prev) => {
        const next = { ...prev };
        d.files.forEach((f) => { if (next[f.name]) next[f.name] = { ...next[f.name], ...f, stale: true }; });
        return next;
      });
      return d;
    } catch (e) { setDataErr(e.message); return null; }
  }, [runId]);

  useEffect(() => {
    setOverview(null); setDocs({}); setTabs([]); setActive(""); setDirty({}); setMarkers({}); setPreview(false);
    load();
  }, [load]);

  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return undefined; }
    load();
    return undefined;
  }, [version, load]);          // a rebuild moved the files: re-read the listing

  // Any tab the user has not edited follows the server after the workspace moves underneath it.
  useEffect(() => {
    if (!overview) return;
    tabsRef.current.forEach((name) => {
      const row = overview.files.find((f) => f.name === name);
      if (!row || editor.current?.isDirty(name)) return;
      api.ideFile(runId, name).then((f) => {
        setDocs((d) => ({ ...d, [name]: { ...d[name], ...row, text: f.text, hash: f.hash, bytes: f.bytes, stale: false } }));
        editor.current?.reset(name, f.text);
      }).catch(() => {});
    });
  }, [overview, runId]);

  useEffect(() => { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); }, [prefs]);

  // The editor is display:none while the preview is up and re-measures itself when it comes back.
  useEffect(() => {
    const t = setTimeout(() => editor.current?.layout(), 80);
    return () => clearTimeout(t);
  }, [preview, sideOpen, showBottom, aiOpen, active]);

  const openFile = useCallback(async (name) => {
    if (tabs.includes(name)) { setActive(name); setPreview(false); return; }
    setBusy("open");
    try {
      const f = await api.ideFile(runId, name);
      setDocs((d) => ({ ...d, [name]: f }));
      setTabs((t) => [...t, name]);
      setActive(name); setPreview(false);
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  }, [runId, tabs, toast]);

  const jump = useCallback(async ({ file, line, column }) => {
    if (!tabs.includes(file)) {
      setBusy("open");
      try {
        const f = await api.ideFile(runId, file);
        setDocs((d) => ({ ...d, [file]: f }));
        setTabs((t) => [...t, file]); setActive(file); setPreview(false);
      } catch (e) { toast(e.message, "error"); setBusy(""); return; }
      setBusy("");
    } else setActive(file);
    setPendingJump({ file, line, column, at: Date.now() });
  }, [runId, tabs]);

  useEffect(() => {
    if (!pendingJump || active !== pendingJump.file) return;
    const t = setTimeout(() => editor.current?.reveal(pendingJump.line, pendingJump.column), 60);
    return () => clearTimeout(t);
  }, [pendingJump, active]);

  const fileTabs = useMemo(() => tabs.map((n) => ({
    name: n, text: docs[n]?.text ?? "", language: docs[n]?.language, editable: !!docs[n]?.editable,
  })), [tabs, docs]);

  /**
   * Write one buffer back. Source files are stored verbatim through the editor API, carrying the digest
   * they were read with so a racing writer is refused. The page's own names go through the patch path:
   * snapshot, sanitize, republish and re-check in Chromium, which spends a revision.
   */
  const saveFile = useCallback(async (name, { quiet } = {}) => {
    const doc = docs[name];
    if (!doc) return false;
    const text = editor.current?.text(name) ?? doc.text;
    if (doc.save_via === "save") {
      try {
        const r = await api.ideSave(runId, name, { text, base_hash: doc.hash || "" });
        setDocs((d) => ({ ...d, [name]: { ...d[name], hash: r.hash, bytes: r.bytes, text, stale: false } }));
        editor.current?.reset(name, text);
        setOverview((o) => (o ? { ...o, files: r.files, undo: r.undo } : o));
        if (!quiet) toast(`${name} saved`, "success");
        return true;
      } catch (e) { toast(e.message, "error"); return false; }
    }
    if (doc.save_via !== "apply") { toast(doc.why || `${name} cannot be written from the editor`, "error"); return false; }
    if (!editable) { toast(`${name} belongs to the page. Patching it needs the run at its approval gate - it is ${run?.status}.`, "error"); return false; }
    try {
      const r = await api.wsApply(runId, { changes: [{ file: name, op: "set", text, note: "saved in the IDE" }],
                                            request: "Saved from the IDE editor.", base_version: version });
      setRun(r);
      editor.current?.reset(name, text);
      if (!quiet) toast(`${name} queued: the page is rebuilding and re-checking`, "success");
      return true;
    } catch (e) { toast(e.message, "error"); return false; }
  }, [docs, runId, version, editable, run?.status, toast, setRun]);

  const saveActive = useCallback(() => { if (active && !preview) saveFile(active); }, [active, preview, saveFile]);

  const saveAll = useCallback(async () => {
    const list = Object.keys(dirty).filter((n) => dirty[n]);
    if (!list.length) { toast("Nothing to save", "success"); return; }
    setBusy("save");
    const sources = list.filter((n) => docs[n]?.save_via === "save");
    const page = list.filter((n) => docs[n]?.save_via === "apply");
    let done = 0;
    for (const n of sources) if (await saveFile(n, { quiet: true })) done += 1;
    if (page.length) {
      if (!editable) toast(`${page.join(", ")} belong to the page - it can only be rebuilt at the approval gate.`, "error");
      else {
        try {
          const changes = page.map((n) => ({ file: n, op: "set", text: editor.current?.text(n) ?? docs[n].text,
                                             note: "saved in the IDE" }));
          const r = await api.wsApply(runId, { changes, request: "Saved from the IDE editor.", base_version: version });
          setRun(r);
          page.forEach((n) => editor.current?.reset(n, changes.find((c) => c.file === n).text));
          done += page.length;
          toast("Page files queued: the build is rebuilding and re-checking", "success");
        } catch (e) { toast(e.message, "error"); }
      }
    }
    setBusy("");
    if (done !== list.length && done) toast(`${done} of ${list.length} file(s) saved`, "error");
    else if (done) toast(`${done} file(s) saved`, "success");
  }, [dirty, docs, editable, runId, version, saveFile, toast, setRun]);

  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key.toLowerCase() === "s") { e.preventDefault(); saveActive(); }
      if (e.key.toLowerCase() === "p") { e.preventDefault(); setPreview((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [saveActive]);

  const closeTab = (name) => {
    if (dirty[name]) { setDiscard(name); return; }
    dropTab(name);
  };
  const dropTab = (name) => {
    setTabs((t) => {
      const rest = t.filter((n) => n !== name);
      setActive((a) => (a === name ? (rest[rest.length - 1] || "") : a));
      return rest;
    });
  };
  const doDiscard = () => { dropTab(discard); setDirty((s) => ({ ...s, [discard]: false })); setDiscard(""); };

  const applyListing = (files, undo) => setOverview((o) => (o ? { ...o, files, undo: undo || o.undo } : o));
  const create = async (name) => {
    setBusy("create");
    try {
      const r = await api.ideCreate(runId, { name, text: `# ${name}\n\nWritten in the IDE.\n`, note: "Created in the IDE" });
      applyListing(r.files, r.undo);
      await openFile(name);
      toast(`${name} created and snapshotted as w${r.snapshot}`, "success");
      return true;
    } catch (e) { toast(e.message, "error"); return false; } finally { setBusy(""); }
  };
  const rename = async (from, to) => {
    setBusy("rename");
    try {
      const r = await api.ideRename(runId, from, to);
      applyListing(r.files, r.undo);
      setTabs((t) => t.map((n) => (n === from ? to : n)));
      setDocs((d) => { const n = { ...d }; const row = n[from]; delete n[from]; if (row) n[to] = { ...row, name: to }; return n; });
      setDirty((s) => { const n = { ...s }; delete n[from]; return n; });
      if (active === from) setActive(to);
      toast(`Renamed to ${to} (w${r.snapshot})`, "success");
      return true;
    } catch (e) { toast(e.message, "error"); return false; } finally { setBusy(""); }
  };
  const remove = async (name) => {
    setBusy("delete");
    try {
      const r = await api.ideDelete(runId, name);
      applyListing(r.files, r.undo);
      setTabs((t) => t.filter((n) => n !== name));
      setDocs((d) => { const n = { ...d }; delete n[name]; return n; });
      if (active === name) setActive("");
      toast(`${name} deleted - w${r.snapshot} still holds it`, "success");
      return true;
    } catch (e) { toast(e.message, "error"); return false; } finally { setBusy(""); }
  };

  const problems = Object.values(markers).flat().filter(Boolean);
  const errorCount = problems.filter((m) => m.severity >= 8).length;
  const activeDoc = docs[active];

  if (err && !run) return <ErrorState title="This run is not available" message={err} retry={refresh} />;

  return (
    <div className={`ide-shell ${sideOpen ? "" : "side-closed"} ${showBottom ? "" : "bottom-closed"} ${aiOpen ? "ai-open" : ""}`}>
      <nav className="ide-activity" aria-label="IDE views">
        {VIEWS.map((v) => (
          <button key={v.id} className={`ide-act ${sideOpen && view === v.id ? "on" : ""}`}
            title={v.label} aria-label={v.label} aria-pressed={sideOpen && view === v.id}
            onClick={() => { if (sideOpen && view === v.id) setSideOpen(false); else { setView(v.id); setSideOpen(true); } }}>
            <Icon name={v.icon} size={20} strokeWidth={1.7} />
            {v.id === "scm" && !!Object.values(dirty).filter(Boolean).length && <span className="ide-act-badge" />}
          </button>
        ))}
        <button className={`ide-act ${aiOpen ? "on" : ""}`} title="AI assistant" aria-label="AI assistant"
          aria-pressed={aiOpen} onClick={() => setAiOpen((o) => !o)}>
          <Icon name="sparkle" size={20} strokeWidth={1.7} />
        </button>
        <button className={`ide-act ${showBottom ? "on" : ""}`} title="Problems and output" aria-label="Problems and output"
          onClick={() => setShowBottom((s) => !s)}>
          <Icon name="alert" size={20} strokeWidth={1.7} />
          {!!errorCount && <span className="ide-act-badge err">{errorCount}</span>}
        </button>
        <button className="ide-act" title="Live preview" aria-label="Live preview" aria-pressed={preview}
          onClick={() => setPreview((p) => !p)}>
          <Icon name="eye" size={20} strokeWidth={1.7} />
        </button>
        <span className="ide-act-spacer" />
        <Link className="ide-act" to="/ide" title="Choose another project" aria-label="Choose another project">
          <Icon name="left" size={20} strokeWidth={1.7} />
        </Link>
      </nav>

      {sideOpen && (
        <aside className="ide-side" aria-label={`${VIEWS.find((v) => v.id === view)?.label || "Explorer"}`}>
          {view === "explorer" && (
            <Explorer files={overview?.files || []} active={active} dirty={dirty}
              changed={overview?.snapshots?.at(-1)?.changed || []} busy={!!busy} limits={overview?.limits}
              onOpen={openFile} onCreate={create} onRename={rename} onDelete={remove} />
          )}
          {view === "search" && (
            <SearchPanel runId={runId} files={overview?.files || []} limits={overview?.limits} onJump={jump} busy={!!busy} />
          )}
          {view === "scm" && (
            <SourceControl runId={runId} overview={overview} dirty={dirty} busy={busy} setBusy={setBusy}
              onMutation={(r) => { if (r) setRun(r); load().then(refresh); }} />
          )}
          {view === "settings" && (
            <div className="ide-panel ide-settings">
              <div className="ide-panel-head"><strong>IDE settings</strong></div>
              <label className="ide-pref">Font size
                <input type="range" min={11} max={20} step={0.5} value={prefs.fontSize}
                  onChange={(e) => setPrefs((p) => ({ ...p, fontSize: Number(e.target.value) }))} />
                <span className="muted small">{prefs.fontSize}px</span>
              </label>
              <label className="ide-check"><input type="checkbox" checked={prefs.wordWrap}
                onChange={(e) => setPrefs((p) => ({ ...p, wordWrap: e.target.checked }))} /> Word wrap</label>
              <label className="ide-check"><input type="checkbox" checked={prefs.minimap}
                onChange={(e) => setPrefs((p) => ({ ...p, minimap: e.target.checked }))} /> Minimap</label>
              <p className="muted small">Saved on this device. Keys: <kbd>Ctrl</kbd>+<kbd>S</kbd> save,
                {" "}<kbd>Ctrl</kbd>+<kbd>H</kbd> replace in file, <kbd>Ctrl</kbd>+<kbd>F</kbd> find,
                {" "}<kbd>Ctrl</kbd>+<kbd>P</kbd> preview.</p>
              <p className="muted small">Model, API keys and run limits live in the backend's settings -
                <Link to="/settings"> Settings</Link> - and are never sent to the browser.</p>
            </div>
          )}
        </aside>
      )}

      <main className="ide-main">
        <header className="ide-toolbar">
          <div className="row wrap ide-toolbar-info">
            <strong className="ide-project">{run?.idea?.slice(0, 48) || "loading…"}</strong>
            {run && <StatusPill status={run.status} />}
            <span className="pill">page v{version}</span>
            {overview && <span className="pill">{overview.files.length} file(s)</span>}
            {overview?.latest_snapshot > 0 && <span className="pill">w{overview.latest_snapshot}</span>}
            {!editable && activeDoc?.save_via === "apply" && <span className="pill warn">page edits wait for the gate</span>}
          </div>
          <div className="row wrap">
            <button className="btn primary small" onClick={saveActive} disabled={!!busy || !active || preview || !dirty[active]}>
              <Icon name="check" size={14} /> Save
            </button>
            <button className="btn ghost small" onClick={saveAll} disabled={!!busy || !Object.values(dirty).some(Boolean)}>
              Save all{Object.values(dirty).some(Boolean) ? ` (${Object.values(dirty).filter(Boolean).length})` : ""}
            </button>
            <button className="btn ghost small" onClick={() => editor.current?.find()} disabled={!active || preview}>
              <Icon name="search" size={14} /> Find
            </button>
            <button className="btn ghost small" onClick={() => editor.current?.replace()} disabled={!active || preview}>
              Replace
            </button>
            <button className="btn ghost small" onClick={() => { setShowBottom(true); }} title="Terminal, problems, build, tests">
              <Icon name="monitor" size={14} /> Output
            </button>
            <Link className="btn ghost small" to={`/runs/${runId}`}><Icon name="rocket" size={14} /> Review, deploy</Link>
          </div>
        </header>

        <div className="ide-body">
          <section className="ide-center">
            <div className="ide-tabs" role="tablist" aria-label="Open files">
              {tabs.map((n) => (
                <button key={n} role="tab" aria-selected={!preview && active === n}
                  className={`ide-tab ${!preview && active === n ? "on" : ""}`} onClick={() => { setActive(n); setPreview(false); }}>
                  <span className="ide-tab-name">{n}</span>
                  {dirty[n] && <span className="ide-flag dot" title="Unsaved">●</span>}
                  <span className="ide-tab-close" role="button" tabIndex={-1} aria-label={`Close ${n}`}
                    onClick={(e) => { e.stopPropagation(); closeTab(n); }}><Icon name="close" size={12} /></span>
                </button>
              ))}
              {preview && (
                <button role="tab" aria-selected className="ide-tab on is-preview" onClick={() => setPreview(true)}>
                  <Icon name="eye" size={13} /> Preview<span className="ide-tab-close" role="button" tabIndex={-1}
                    aria-label="Close preview" onClick={(e) => { e.stopPropagation(); setPreview(false); }}><Icon name="close" size={12} /></span>
                </button>
              )}
            </div>

            {dataErr && <ErrorState title="Couldn’t read this workspace" message={dataErr} retry={load} />}
            {!dataErr && !overview && <div className="card skeleton" style={{ height: 180 }} />}
            {overview && !overview.files.length && (
              <EmptyState icon="code" title="No files published yet"
                text="The editor opens what a run publishes. This run has not built a page yet." />
            )}

            <div className={`ide-editor ${preview || !active ? "is-hidden" : ""}`}>
              <MonacoEditor ref={editor} tabs={fileTabs} active={active} theme={theme}
                onDirty={(name, is) => setDirty((d) => ({ ...d, [name]: is }))}
                onMarkers={(name, list) => setMarkers((m) => ({ ...m, [name]: list }))}
                onCursor={(c) => setCursor({ line: c.line, column: c.column })}
                onSave={saveActive} prefs={prefs} />
            </div>

            {preview && (
              <div className="ide-preview">
                <LivePreview runId={runId} version={version} working={working} />
              </div>
            )}

            {!preview && !active && !!overview?.files?.length && (
              <div className="ide-welcome">
                <EmptyState icon="ide" title="Open a file"
                  text="Pick one in the Explorer, or search across the workspace. Every tab is a file this run publishes." />
              </div>
            )}
          </section>
        </div>

        {showBottom && (
          <BottomPanel runId={runId} overview={overview} run={run} markers={markers} events={events}
            connected={connected} onJump={jump} busy={busy} setBusy={setBusy} />
        )}
      </main>

      {aiOpen && (
        <AssistantPanel runId={runId} version={version} files={overview?.files || []}
          editable={editable} working={working} undo={overview?.undo}
          setRun={setRun} refresh={refresh} onClose={() => setAiOpen(false)} />
      )}

      <footer className="ide-status">
        <span className="muted small">{run ? `${run.status.replace(/_/g, " ")}` : "…"}</span>
        {activeDoc && <span className="muted small mono">{active} · {activeDoc.kind} · {activeDoc.language || "text"}</span>}
        {!preview && active && <span className="muted small">{cursor.line}:{cursor.column}</span>}
        <span className={`muted small ${errorCount ? "err-text" : ""}`}>{errorCount} error(s),
          {" "}{problems.filter((m) => m.severity === 4).length} warning(s)</span>
        <span className="muted small">{connected ? "live" : "polling"} · {events.length} event(s)</span>
        {working && <span className="pill warn">crew is working</span>}
      </footer>

      <ConfirmModal open={!!discard} onClose={() => setDiscard("")} onConfirm={doDiscard} danger
        confirmLabel="Close without saving" title={`Discard changes in ${discard}?`}
        message="The stored file is unchanged - what is lost is only what you typed in this tab since the last save." />
    </div>
  );
}
