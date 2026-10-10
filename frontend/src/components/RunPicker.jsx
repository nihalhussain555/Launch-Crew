import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import StatusPill from "./StatusPill";
import { timeAgo } from "../utils";

const KEY = "lc_last_run";
const SCAN = 10;   // most recently used projects searched for the saved run

/** The chosen run lives in ?run= so every page here is deep-linkable; localStorage keeps it between visits. */
export function useRunPick() {
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") || localStorage.getItem(KEY) || "";
  const setRunId = (id) => {
    if (id) localStorage.setItem(KEY, id); else localStorage.removeItem(KEY);
    const next = new URLSearchParams(params);
    if (id) next.set("run", id); else next.delete("run");
    setParams(next, { replace: true });
  };
  return { runId, setRunId };
}

/**
 * Project + run selectors built from the two endpoints that actually list them
 * (GET /api/projects and GET /api/projects/{id}). The chosen run drives the workspace, version,
 * quality and chat pages, so a run with no published files yet is still a valid choice.
 */
export default function RunPicker({ runId, onPick, note }) {
  const [projects, setProjects] = useState(null);
  const [picked, setPicked] = useState({ projectId: "", runs: null });
  const [err, setErr] = useState("");

  const loadRuns = (projectId, list) => setPicked({ projectId, runs: list });

  const retryProjects = () => {
    setErr(""); setProjects(null); setPicked({ projectId: "", runs: null });
    api.listProjects().then(setProjects).catch((e) => setErr(e.message));
  };
  useEffect(() => { retryProjects(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Resolve which project the current run belongs to, then hand its run list to the selects.
  useEffect(() => {
    if (!projects) return;
    if (!projects.length) { loadRuns("", []); return undefined; }
    let live = true;
    (async () => {
      if (runId) {
        for (const p of projects.slice(0, SCAN)) {
          try {
            const d = await api.getProject(p.id);
            if (!live) return;
            if ((d.runs || []).some((r) => r.id === runId)) { loadRuns(p.id, d.runs); return; }
          } catch { /* this project is unreadable; the next one may hold the run */ }
        }
      }
      if (!live || picked.projectId) return;
      const d = await api.getProject(projects[0].id).catch(() => null);
      if (live) loadRuns(projects[0].id, d?.runs || []);
    })();
    return () => { live = false; };
  }, [projects]); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseProject = async (projectId) => {
    loadRuns(projectId, null);
    const d = await api.getProject(projectId).catch((e) => { setErr(e.message); loadRuns(projectId, []); return null; });
    if (d) loadRuns(projectId, d.runs || []);
  };

  // Adopt a run once per project load: keep the saved pick when this project has it.
  useEffect(() => {
    if (!picked.runs) return;
    const match = picked.runs.find((r) => r.id === runId);
    if (!match && (picked.runs[0]?.id || "") !== runId) onPick(picked.runs[0]?.id || "");
  }, [picked.runs]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = picked.runs?.find((r) => r.id === runId);

  return (
    <section className="card picker-card">
      <div className="row wrap between">
        <div className="row wrap picker-fields">
          <label className="pick">
            <span className="muted small">Project</span>
            <select value={picked.projectId} aria-label="Project"
              onChange={(e) => chooseProject(e.target.value)}>
              {!projects && <option value="">Loading…</option>}
              {projects && !projects.length && <option value="">No projects yet</option>}
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="pick">
            <span className="muted small">Run</span>
            <select value={runId} aria-label="Run"
              onChange={(e) => onPick(e.target.value)} disabled={!picked.runs?.length}>
              {!picked.runs && <option value="">Loading…</option>}
              {picked.runs && !picked.runs.length && <option value="">No runs in this project</option>}
              {picked.runs?.map((r) => (
                <option key={r.id} value={r.id}>
                  {(r.idea || "Untitled").slice(0, 54)} · {r.status.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
        </div>
        {current && (
          <div className="row wrap picker-state">
            <StatusPill status={current.status} />
            {current.score != null && <span className="pill">{current.score}/100</span>}
            <span className="muted small">{timeAgo(current.created_at)} · {current.tokens_used.toLocaleString()} tokens</span>
            <Link className="btn ghost small" to={`/runs/${current.id}`}><Icon name="eye" size={14} /> Open run</Link>
          </div>
        )}
      </div>
      {note && <p className="muted small">{note}</p>}
      {err && !projects && <ErrorState title="Couldn’t load your projects" message={err} retry={retryProjects} />}
      {projects && !projects.length && (
        <EmptyState icon="rocket" title="No projects yet" text="Launch an idea and every workspace page here fills in with its files, versions and reports."
          action={<Link to="/dashboard" className="btn primary">Start an idea</Link>} />
      )}
    </section>
  );
}
