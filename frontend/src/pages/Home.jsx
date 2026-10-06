import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import IdeaForm from "../components/IdeaForm";

export default function Home() {
  const nav = useNavigate();
  const [projects, setProjects] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.listProjects().then(setProjects).catch((e) => setErr(e.message)); }, []);

  const start = async (idea) => {
    setBusy(true); setErr("");
    try {
      const p = await api.createProject(idea);
      const run = await api.createRun(p.id);
      nav(`/runs/${run.id}`);
    } catch (e) { setErr(e.message); setBusy(false); }
  };
  const rerun = async (p) => {
    try { nav(`/runs/${(await api.createRun(p.id)).id}`); } catch (e) { setErr(e.message); }
  };
  const open = async (p) => {
    try { const d = await api.getProject(p.id); d.runs.length ? nav(`/runs/${d.runs[0].id}`) : rerun(p); } catch (e) { setErr(e.message); }
  };

  return (
    <>
      <IdeaForm onSubmit={start} busy={busy} />
      {err && <div className="error" role="alert">{err}</div>}
      <h2>Your projects</h2>
      {projects === null && !err && <div className="muted">Loading…</div>}
      {projects?.length === 0 && <div className="card muted">No projects yet. Type an idea above to get started.</div>}
      <div className="list">
        {projects?.map((p) => (
          <div className="card row between" key={p.id}>
            <div><strong>{p.name}</strong><div className="muted small">{new Date(p.created_at).toLocaleString()}</div></div>
            <div className="row"><button className="btn ghost" onClick={() => open(p)}>Open latest</button>
              <button className="btn ghost" onClick={() => rerun(p)}>New run</button></div>
          </div>
        ))}
      </div>
    </>
  );
}
