import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import EmptyState from "../components/EmptyState";
import IdeaForm from "../components/IdeaForm";
import Icon from "../components/Icon";
import ScoreRing from "../components/ScoreRing";
import StatusPill from "../components/StatusPill";
import { useStartRun } from "../hooks/useStartRun";
import { compact, timeAgo } from "../utils";

function Stat({ icon, label, value, children }) {
  return (
    <div className="card stat">
      <span className="stat-icon" aria-hidden="true">{icon}</span>
      <div><div className="stat-num">{children ?? value}</div><div className="muted small">{label}</div></div>
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const nav = useNavigate();
  const { start, busy } = useStartRun();
  const [stats, setStats] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.stats().then(setStats).catch((e) => setErr(e.message)); }, []);
  const first = (user?.name || user?.email || "").split(/[ @]/)[0];

  return (
    <>
      <div className="page-head">
        <div><h1>Welcome back{first ? `, ${first}` : ""}</h1><p className="muted">Turn an idea into a tested, launch-ready page.</p></div>
      </div>

      <section className="card hero-card" data-tour="idea">
        <h2>What are we launching?</h2>
        <IdeaForm onSubmit={start} busy={busy} />
        <p className="muted small">Not sure what to build? <Link to="/templates">Browse idea templates <Icon name="arrowRight" size={14} /></Link></p>
      </section>

      {err && <div className="error" role="alert">{err}</div>}
      <div className="grid-stats" data-tour="stats">
        {!stats ? [0, 1, 2, 3, 4].map((i) => <div key={i} className="card skeleton" style={{ height: 84 }} />) : (
          <>
            <Stat icon={<Icon name="folder" size={22} />} label="Projects" value={stats.projects} />
            <Stat icon={<Icon name="rocket" size={22} />} label="Runs" value={stats.runs} />
            <Stat icon={<Icon name="deploy" size={22} />} label="Deployed" value={stats.deployed} />
            <Stat icon={<Icon name="target" size={22} />} label="Avg readiness">
              {stats.avg_readiness == null ? "-" : <ScoreRing value={stats.avg_readiness} size={44} stroke={5} />}
            </Stat>
            <Stat icon={<Icon name="hash" size={22} />} label="Tokens used" value={compact(stats.tokens)} />
          </>
        )}
      </div>

      <section>
        <div className="row between"><h2>Recent runs</h2><Link to="/projects">All projects <Icon name="arrowRight" size={14} /></Link></div>
        {stats && stats.recent_runs.length === 0 && (
          <EmptyState icon="rocket" title="No runs yet" text="Type an idea above and watch the crew work." />
        )}
        <div className="list">
          {stats?.recent_runs.map((r) => (
            <button key={r.id} className="card run-row" onClick={() => nav(`/runs/${r.id}`)}>
              <div className="run-main"><strong>{r.idea}</strong><span className="muted small">{timeAgo(r.created_at)}</span></div>
              <div className="row"><StatusPill status={r.status} />{r.score != null && <ScoreRing value={r.score} size={40} stroke={5} />}</div>
            </button>
          ))}
        </div>
      </section>
    </>
  );
}