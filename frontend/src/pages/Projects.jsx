import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

export default function Projects() {
  const nav = useNavigate();
  const toast = useToast();
  const [projects, setProjects] = useState(null);
  const [q, setQ] = useState("");
  const [target, setTarget] = useState(null);
  const [err, setErr] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => { setErr(""); api.listProjects().then(setProjects).catch((e) => setErr(e.message)); }, [tick]);
  const shown = useMemo(() => (projects || []).filter((p) => `${p.name} ${p.idea}`.toLowerCase().includes(q.trim().toLowerCase())), [projects, q]);

  const newRun = async (p) => {
    try { nav(`/runs/${(await api.createRun(p.id)).id}`); } catch (e) { toast(e.message, "error"); }
  };
  const remove = async () => {
    try { await api.deleteProject(target.id); setProjects((l) => l.filter((x) => x.id !== target.id)); toast("Project deleted", "success"); }
    catch (e) { toast(e.message, "error"); }
    setTarget(null);
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Projects</h1><p className="muted">Every idea you have launched or are working on.</p></div>
        <Link to="/dashboard" className="btn primary"><Icon name="plus" size={15} /> New idea</Link>
      </div>
      <input className="search-input" placeholder="Search projects…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search projects" />
      {err && <ErrorState title="Couldn’t load your projects" message={err} retry={() => setTick((t) => t + 1)} />}
      {!projects && !err && <div className="grid-cards">{[0, 1, 2].map((i) => <div key={i} className="card skeleton" style={{ height: 150 }} />)}</div>}
      {projects && projects.length === 0 && (
        <EmptyState icon="folder" title="No projects yet" text="Start with an idea and your first project appears here."
          action={<Link to="/dashboard" className="btn primary">Start your first idea</Link>} />
      )}
      {projects && projects.length > 0 && shown.length === 0 && <EmptyState icon="search" title="No matches" text={`Nothing matches “${q}”.`} />}
      <div className="grid-cards">
        {shown.map((p) => (
          <article key={p.id} className="card proj-card">
            <Link to={`/projects/${p.id}`} className="proj-title">{p.name}</Link>
            <p className="muted clamp">{p.idea}</p>
            <span className="muted small">Created {timeAgo(p.created_at)}</span>
            <div className="row wrap">
              <Link to={`/projects/${p.id}`} className="btn ghost small">Open</Link>
              <button className="btn ghost small" onClick={() => newRun(p)}>New run</button>
              <button className="btn ghost small danger-text" onClick={() => setTarget(p)}>Delete</button>
            </div>
          </article>
        ))}
      </div>
      <ConfirmModal open={!!target} onClose={() => setTarget(null)} onConfirm={remove} danger confirmLabel="Delete project"
        title="Delete this project?" message={target ? `“${target.name}” and all of its runs, screenshots and feedback will be permanently deleted.` : ""} />
    </>
  );
}