import { useState } from "react";
import { api } from "../../api";
import Icon from "../Icon";

/**
 * Workspace search over `GET /workspace/search`: the real stored bytes, deterministic, no model.
 *
 * A jump opens the file and places the cursor at the match. Replacing across files is deliberately not
 * offered here - it would need an endpoint that writes several files in one step, and the patch path
 * already does that with a plan, a snapshot and a re-check. Per-file replace is the editor's own Ctrl+H.
 */
export default function SearchPanel({ runId, files, limits, onJump, busy }) {
  const [q, setQ] = useState("");
  const [scope, setScope] = useState("");
  const [regex, setRegex] = useState(false);
  const [caseSensitive, setCaseSensitive] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [working, setWorking] = useState(false);

  const search = async (e) => {
    e?.preventDefault();
    const needle = q.trim();
    if (!needle) { setErr("Type something to search for."); setResult(null); return; }
    setWorking(true); setErr(""); setResult(null);
    try { setResult(await api.ideSearch(runId, { q: needle, file: scope, regex, caseSensitive })); }
    catch (ex) { setErr(ex.message); } finally { setWorking(false); }
  };

  const byFile = (result?.matches || []).reduce((acc, m) => {
    (acc[m.file] ||= []).push(m);
    return acc;
  }, {});

  return (
    <div className="ide-panel ide-search">
      <div className="ide-panel-head"><strong>Search</strong>
        {result && <span className="muted">{result.counts.matches} in {result.counts.files} file(s)</span>}
      </div>
      <form className="stack" onSubmit={search}>
        <input value={q} onChange={(e) => setQ(e.target.value)} maxLength={limits?.search?.max_query || 200}
          placeholder={regex ? "regular expression" : "text in any file"} aria-label="Search the workspace" />
        <select value={scope} onChange={(e) => setScope(e.target.value)} aria-label="Search scope">
          <option value="">All files</option>
          {files.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
        </select>
        <div className="row wrap ide-search-flags">
          <label className="ide-check"><input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} /> Regex</label>
          <label className="ide-check"><input type="checkbox" checked={caseSensitive} onChange={(e) => setCaseSensitive(e.target.checked)} /> Match case</label>
          <button className="btn primary small" type="submit" disabled={working || busy}>
            <Icon name="search" size={14} /> {working ? "Searching…" : "Search"}
          </button>
        </div>
      </form>
      {err && <p className="ide-form-problem" role="alert">{err}</p>}
      {result && (
        <>
          <p className="muted small">Scanned {result.counts.scanned} file(s) as they are stored{result.scope === "all files" ? "" : ` (only ${result.scope})`}
            {result.truncated ? ` · stopped at ${result.reason}` : ""}</p>
          {!result.matches.length && <p className="muted small ide-panel-empty">No match for “{result.query}”.</p>}
          {Object.entries(byFile).map(([name, list]) => (
            <section key={name} className="ide-hit-group">
              <h4 className="mono">{name}<span className="muted">{list.length}</span></h4>
              {list.map((m, i) => (
                <button key={`${m.line}-${i}`} className="ide-hit" onClick={() => onJump({ file: name, line: m.line, column: m.column })}>
                  <span className="ide-hit-pos">{m.line}:{m.column}</span>
                  <span className="ide-hit-text mono">{m.text}</span>
                </button>
              ))}
            </section>
          ))}
          {(result.skipped || []).map((s, i) => (
            <p key={i} className="muted small ide-form-problem">Skipped {s.file}: {s.reason}</p>
          ))}
        </>
      )}
      <p className="muted small ide-tree-note">
        Replace inside a file with <kbd>Ctrl</kbd>+<kbd>H</kbd> in the editor. Across files, write the change
        through the patch path so it is planned, snapshotted and re-checked.
      </p>
    </div>
  );
}
