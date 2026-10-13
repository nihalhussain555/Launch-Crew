import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import StatusPill from "../components/StatusPill";
import { timeAgo } from "../utils";

const RECENTS_KEY = "lc_ide_recents";
const RECENTS_MAX = 6;
const THUMB_LIMIT = 8;   // screenshots are fetched per card, so only the first rows ask for one

const FILTERS = [
  { id: "all", label: "All projects", test: () => true },
  { id: "editable", label: "Open in IDE", test: (p) => p.can_open },
  { id: "gate", label: "Awaiting approval", test: (p) => p.status === "awaiting_approval" },
  { id: "deployed", label: "Deployed", test: (p) => p.status === "deployed" },
  { id: "building", label: "Building", test: (p) => ["queued", "running", "deploying"].includes(p.status) },
];
const SORTS = [
  { id: "recent", label: "Last modified", cmp: (a, b) => Date.parse(b.last_modified || 0) - Date.parse(a.last_modified || 0) },
  { id: "name", label: "Name", cmp: (a, b) => a.name.localeCompare(b.name) },
  { id: "files", label: "Most files", cmp: (a, b) => b.files - a.files },
  { id: "score", label: "Launch readiness", cmp: (a, b) => (b.readiness ?? -1) - (a.readiness ?? -1) },
];

/** The picker writes this so the next visit can offer "resume" without another request. */
function readRecents() {
  try { return JSON.parse(localStorage.getItem(RECENTS_KEY) || "[]").slice(0, RECENTS_MAX); }
  catch { return []; }
}

export function rememberRecent(row) {
  const run = row.open_run || row.latest_run;
  if (!run || !row.can_open) return;
  const entry = { project_id: row.project_id, run_id: run.run_id, name: row.name, version: run.version, at: new Date().toISOString() };
  localStorage.setItem(RECENTS_KEY, JSON.stringify([entry, ...readRecents().filter((r) => r.run_id !== entry.run_id)].slice(0, RECENTS_MAX)));
}

/** A run's desktop screenshot, fetched from the authenticated endpoint and released on unmount. */
function Thumb({ runId, wanted }) {
  const [url, setUrl] = useState("");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true, objectUrl = "";
    setUrl(""); setFailed(false);
    if (!wanted || !runId) return undefined;
    api.screenshotUrl(runId, "desktop").then((u) => {
      if (!live) { URL.revokeObjectURL(u); return undefined; }
      objectUrl = u; setUrl(u); return u;
    }).catch(() => live && setFailed(true));
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [runId, wanted]);

  if (url) return <img className="ide-thumb-img" src={url} alt="" loading="lazy" />;
  return (
    <div className="ide-thumb-empty" aria-hidden="true">
      <Icon name={failed ? "alert" : "monitor"} size={20} strokeWidth={1.5} />
      <span>{failed ? "No screenshot stored for this run" : "Loading preview…"}</span>
    </div>
  );
}

/**
 * The IDE's front door: every project you own, with the exact run "Open in IDE" would load.
 * Nothing here is a mock-up - the list, the version counts and the blocked reasons all come from
 * GET /api/ide/projects, which reads the same workspace the editor opens.
 */
export default function IdeHome() {
  const nav = useNavigate();
  const [feed, setFeed] = useState(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("recent");
  const [importInfo, setImportInfo] = useState(null);
  const [recents, setRecents] = useState(readRecents);

  const load = () => {
    setErr(""); setFeed(null);
    api.ideProjects().then(setFeed).catch((e) => setErr(e.message));
  };
  useEffect(() => { load(); }, []);                       // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { api.ideImportStatus().then(setImportInfo).catch(() => setImportInfo(null)); }, []);

  const open = (row) => {
    if (!row.can_open) return;
    rememberRecent(row);
    setRecents(readRecents());
    nav(`/ide/${row.open_run.run_id}`);
  };

  const shown = useMemo(() => {
    if (!feed) return [];
    const needle = q.trim().toLowerCase();
    const test = (FILTERS.find((f) => f.id === filter) || FILTERS[0]).test;
    const cmp = (SORTS.find((s) => s.id === sort) || SORTS[0]).cmp;
    return feed.projects
      .filter((p) => test(p))
      .filter((p) => !needle || `${p.name} ${p.description} ${p.framework} ${(p.languages || []).join(" ")}`.toLowerCase().includes(needle))
      .sort(cmp);
  }, [feed, q, filter, sort]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Code IDE</h1>
          <p className="muted">Pick a project and its newest published run opens in the editor - real files,
            real saves, the same workspace the crew builds.</p>
        </div>
        <div className="row wrap">
          <Link to="/new" className="btn primary"><Icon name="plus" size={15} /> New project</Link>
          <Link to="/workspace" className="btn ghost"><Icon name="code" size={15} /> Workspace tools</Link>
        </div>
      </div>

      {recents.length > 0 && (
        <section className="ide-recents" aria-label="Recently opened">
          <span className="muted small"><Icon name="refresh" size={13} /> Recent</span>
          {recents.map((r) => (
            <Link key={r.run_id} to={`/ide/${r.run_id}`} className="chip" onClick={() => {
              const row = feed?.projects.find((p) => p.project_id === r.project_id);
              if (row) rememberRecent(row);
            }}>{r.name.slice(0, 28)}{r.version ? ` · v${r.version}` : ""}</Link>
          ))}
          <button className="btn ghost small" onClick={() => { localStorage.removeItem(RECENTS_KEY); setRecents([]); }}>
            Clear
          </button>
        </section>
      )}

      <div className="ide-controls">
        <input className="search-input" placeholder="Search projects, files or stacks…" value={q}
          onChange={(e) => setQ(e.target.value)} aria-label="Search projects" />
        <div className="row wrap" role="group" aria-label="Filter projects">
          {FILTERS.map((f) => (
            <button key={f.id} className={`chip ${filter === f.id ? "on" : ""}`} onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
        </div>
        <label className="row">
          <span className="muted small">Sort</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort projects">
            {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </label>
      </div>

      {err && <ErrorState title="Couldn’t load your projects" message={err} retry={load} />}
      {!feed && !err && (
        <div className="grid-cards">{[0, 1, 2, 3].map((i) => <div key={i} className="card skeleton" style={{ height: 230 }} />)}</div>
      )}
      {feed && !feed.projects.length && (
        <EmptyState icon="folder" title="No projects yet"
          text="The IDE edits the workspace a run publishes, so start an idea first - it appears here the moment it has files."
          action={<Link to="/new" className="btn primary">Create a project</Link>} />
      )}
      {feed && feed.projects.length > 0 && !shown.length && (
        <EmptyState icon="search" title="Nothing matches" text={`No project matches “${q}” in this filter.`}
          action={<button className="btn ghost" onClick={() => { setQ(""); setFilter("all"); }}>Reset filters</button>} />
      )}

      <div className="grid-cards ide-grid">
        {shown.map((p, i) => {
          const run = p.open_run || p.latest_run;
          return (
            <article key={p.project_id} className={`card ide-card ${p.can_open ? "" : "is-locked"}`}>
              <div className="ide-thumb">
                <Thumb runId={run?.run_id} wanted={i < THUMB_LIMIT && !!run?.files} />
                {run?.files > 0 && <span className="ide-thumb-badge">v{run.version} · {run.files} files</span>}
              </div>
              <div className="ide-card-body">
                <h3 className="ide-card-title">{p.name}</h3>
                <p className="muted clamp">{p.description}</p>
                <div className="row wrap ide-meta">
                  {run ? <StatusPill status={run.status} /> : <span className="pill">No runs</span>}
                  {p.readiness != null && <span className="pill">{p.readiness}/100</span>}
                  {p.style_label && <span className="pill">{p.style_label}</span>}
                  {p.can_open && !p.can_write && <span className="pill warn">Read only</span>}
                </div>
                <dl className="ide-specs">
                  <div><dt>Stack</dt><dd>{p.framework}</dd></div>
                  <div><dt>Languages</dt><dd>{(p.languages || []).join(", ") || "—"}</dd></div>
                  <div><dt>Runs</dt><dd>{p.run_count}</dd></div>
                  <div><dt>Modified</dt><dd>{p.last_modified ? timeAgo(p.last_modified) : "—"}</dd></div>
                </dl>
                {p.can_open
                  ? (
                    <div className="row wrap">
                      <button className="btn primary small" onClick={() => open(p)}><Icon name="code" size={14} /> Open in IDE</button>
                      <Link className="btn ghost small" to={`/runs/${run.run_id}`}><Icon name="eye" size={14} /> Run detail</Link>
                      <Link className="btn ghost small" to={`/workspace?run=${run.run_id}`}><Icon name="layers" size={14} /> Workspace</Link>
                    </div>
                  )
                  : <p className="muted small ide-blocked"><Icon name="alert" size={14} /> {p.blocked_reason}</p>}
              </div>
            </article>
          );
        })}
      </div>

      {importInfo && (
        <section className="card ide-import" aria-label="Import">
          <h3><Icon name="link" size={16} /> Import a project</h3>
          <p className="muted small">{importInfo.supported?.[0]?.how}</p>
          <ul className="ide-import-list">
            {(importInfo.unsupported || []).map((u) => (
              <li key={u.kind}>
                <strong>{u.kind}</strong>
                <span className="muted small">{u.reason}</span>
                <span className="muted small">Would need: {u.would_need}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
