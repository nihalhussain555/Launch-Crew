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
  // Feature work is counted out of each run's own record, so a run only appears here if it carries a
  // request, an undecided proposal or an applied build - and none of those words means "live".
  const featureRuns = (stats?.recent_runs || []).filter((r) => r.feature_asked || r.feature_open || r.feature_built);

  return (
    <>
      <div className="page-head">
        <div><h1>Welcome back{first ? `, ${first}` : ""}</h1><p className="muted">Turn an idea into a tested, launch-ready page.</p></div>
        <Link to="/new" className="btn primary"><Icon name="sliders" size={15} /> New project brief</Link>
      </div>

      <section className="card hero-card" data-tour="idea">
        <h2>What are we launching?</h2>
        <IdeaForm onSubmit={start} busy={busy} />
        <p className="muted small">
          This quick start leaves the site type, style and sections to the crew. To choose them yourself:{" "}
          <Link to="/new">write a full brief</Link> or{" "}
          <Link to="/templates">browse idea templates <Icon name="arrowRight" size={14} /></Link>
        </p>
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

      {!!featureRuns.length && (
        <section className="card stack" aria-label="Feature work across your runs">
          <div className="row between wrap">
            <h2>Feature work</h2>
            <span className="muted small">Counted from each run’s own record, never assumed</span>
          </div>
          <div className="list">
            {featureRuns.map((r) => (
              <div key={r.id} className="plan-item">
                <div className="row wrap between">
                  <strong>{r.idea}</strong>
                  <StatusPill status={r.status} />
                </div>
                <div className="row wrap">
                  {!!r.feature_asked && <span className="pill">{r.feature_asked} asked in the brief</span>}
                  {!!r.feature_open && <span className="pill warn">{r.feature_open} awaiting your decision</span>}
                  {!!r.feature_built && <span className="pill ok">{r.feature_built} applied build(s)</span>}
                  <Link className="btn ghost small" to={`/workspace?run=${r.id}`}>
                    <Icon name="code" size={14} /> Feature studio
                  </Link>
                </div>
              </div>
            ))}
          </div>
          <p className="muted small">A count is not a claim that anything works. “Asked” means the brief recorded a
            request and no build has been reviewed yet; “applied” means a measured patch went through the workspace
            pipeline, and a later crew revision can still have redrawn the page without those panels. The studio
            reads the page itself and says which of its features are live, which need your server started, and
            which need a key you have not set.</p>
        </section>
      )}

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