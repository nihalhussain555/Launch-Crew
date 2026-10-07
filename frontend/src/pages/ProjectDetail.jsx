import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import ScoreRing from "../components/ScoreRing";
import StatusPill from "../components/StatusPill";
import { useToast } from "../toast";
import { compact, fmtDate } from "../utils";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [del, setDel] = useState(false);

  useEffect(() => { setP(null); api.getProject(projectId).then(setP).catch((e) => setErr(e.message)); }, [projectId]);

  if (err) return <ErrorState title="Project not available" message={err} back="/projects" backLabel="Back to projects" />;
  if (!p) return <div className="card skeleton" style={{ height: 220 }} />;

  const scored = [...p.runs].reverse().filter((r) => r.score != null);
  const newRun = async () => {
    setBusy(true);
    try { nav(`/runs/${(await api.createRun(p.id)).id}`); } catch (e) { toast(e.message, "error"); setBusy(false); }
  };
  const remove = async () => {
    try { await api.deleteProject(p.id); toast("Project deleted", "success"); nav("/projects"); }
    catch (e) { toast(e.message, "error"); setDel(false); }
  };

  return (
    <>
      <div className="page-head">
        <div><Link to="/projects" className="muted small"><Icon name="left" size={13} /> Projects</Link><h1>{p.name}</h1><p className="muted">{p.idea}</p></div>
        <div className="row"><button className="btn primary" onClick={newRun} disabled={busy}>{busy ? "Starting…" : <><Icon name="rocket" size={16} /> New run</>}</button>
          <button className="btn ghost danger-text" onClick={() => setDel(true)}>Delete</button></div>
      </div>

      {scored.length > 1 && (
        <section className="card">
          <h2>Readiness over runs</h2>
          <div className="bars" role="img" aria-label="Readiness score per run, oldest to newest">
            {scored.map((r, i) => (
              <div key={r.id} className="bar-col" title={`${fmtDate(r.created_at)}: ${r.score}`}>
                <div className={`bar-fill ${r.score >= 85 ? "ok" : r.score >= 65 ? "warn" : "err"}`} style={{ height: `${r.score}%` }} />
                <span className="small muted">#{i + 1}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <h2>Runs</h2>
        {p.runs.length === 0 && <EmptyState icon="rocket" title="No runs yet" text="Start a run to generate the page." />}
        <div className="list">
          {p.runs.map((r) => (
            <Link key={r.id} to={`/runs/${r.id}`} className="card run-row">
              <div className="run-main"><strong>{fmtDate(r.created_at)}</strong><span className="muted small">{compact(r.tokens_used)} tokens</span></div>
              <div className="row"><StatusPill status={r.status} />{r.score != null && <ScoreRing value={r.score} size={40} stroke={5} />}</div>
            </Link>
          ))}
        </div>
      </section>
      <ConfirmModal open={del} onClose={() => setDel(false)} onConfirm={remove} danger confirmLabel="Delete project"
        title="Delete this project?" message="All runs, screenshots and feedback for this project will be permanently deleted." />
    </>
  );
}