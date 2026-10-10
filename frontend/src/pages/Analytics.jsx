import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import RunPicker, { useRunPick } from "../components/RunPicker";
import ScoreRing from "../components/ScoreRing";
import StatusPill from "../components/StatusPill";
import { useRun } from "../hooks/useRun";
import { compact, fmtDate, timeAgo } from "../utils";

const TONE_OF = (score) => (score == null ? "" : score >= 80 ? "ok" : score >= 60 ? "warn" : "err");

function Stat({ icon, label, value, children }) {
  return (
    <div className="card stat">
      <span className="stat-icon" aria-hidden="true">{icon}</span>
      <div><div className="stat-num">{children ?? value}</div><div className="muted small">{label}</div></div>
    </div>
  );
}

/** Account usage from the usage endpoint, plus the depth one run carries: files, snapshots, edits and tokens. */
export default function Analytics() {
  const { runId, setRunId } = useRunPick();
  const { run, err, refresh } = useRun(runId);
  const [stats, setStats] = useState(null);
  const [loadErr, setLoadErr] = useState("");

  const load = () => { setLoadErr(""); api.stats().then(setStats).catch((e) => setLoadErr(e.message)); };
  useEffect(load, []);

  const s = run?.state || {};
  const recent = stats?.recent_runs || [];
  const byStatus = recent.reduce((m, r) => ({ ...m, [r.status]: (m[r.status] || 0) + 1 }), {});
  const scored = recent.filter((r) => r.score != null);
  const fileBytes = (s.files || []).reduce((n, f) => n + (f.bytes || 0), 0);
  const maxScore = 100;

  return (
    <>
      <div className="page-head">
        <div><h1>Analytics &amp; Usage</h1><p className="muted">What the crew has built and what it cost to build it.</p></div>
        <Link to="/settings" className="btn ghost small"><Icon name="gear" size={15} /> Settings</Link>
      </div>

      {loadErr && <ErrorState title="Couldn’t read your usage" message={loadErr} retry={load} />}
      {!stats && !loadErr && <div className="grid-stats">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="card skeleton" style={{ height: 84 }} />)}</div>}

      {stats && (
        <>
          <div className="grid-stats">
            <Stat icon={<Icon name="folder" size={22} />} label="Projects" value={stats.projects} />
            <Stat icon={<Icon name="rocket" size={22} />} label="Runs" value={stats.runs} />
            <Stat icon={<Icon name="deploy" size={22} />} label="Deployed" value={stats.deployed} />
            <Stat icon={<Icon name="hash" size={22} />} label="Tokens used" value={compact(stats.tokens)} />
            <Stat icon={<Icon name="target" size={22} />} label="Avg readiness">
              {stats.avg_readiness == null ? "—" : <ScoreRing value={stats.avg_readiness} size={44} stroke={5} />}
            </Stat>
          </div>

          <div className="grid2">
            <section className="card stack">
              <h2>Readiness of recent runs</h2>
              {!scored.length ? <p className="muted small">None of the recent runs has a readiness score yet.</p> : (
                <div className="bars" role="img" aria-label={`Readiness scores for ${scored.length} recent run(s)`}>
                  {scored.slice().reverse().map((r) => (
                    <div key={r.id} className="bar-col" title={`${r.idea.slice(0, 60)} — ${r.score}/100`}>
                      <span className="muted small">{r.score}</span>
                      <div className={`bar-fill ${TONE_OF(r.score)}`} style={{ height: `${(r.score / maxScore) * 100}%` }} />
                    </div>
                  ))}
                </div>
              )}
              <p className="muted small">The eight most recent runs, as the usage endpoint reports them. A run scores
                nothing until the crew assesses it.</p>
              <ul className="file-list">
                {recent.map((r) => (
                  <li key={r.id} className="file-item">
                    <div className="row wrap between">
                      <div className="run-main">
                        <strong>{r.idea}</strong>
                        <span className="muted small">{timeAgo(r.created_at)} · {fmtDate(r.created_at)}</span>
                      </div>
                      <div className="row wrap">
                        <StatusPill status={r.status} />
                        {r.score != null && <span className={`pill ${TONE_OF(r.score)}`}>{r.score}/100</span>}
                        <Link className="btn ghost small" to={`/runs/${r.id}`}><Icon name="arrowRight" size={14} /> Open</Link>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            <section className="card stack">
              <h2>Run states</h2>
              {Object.entries(byStatus).map(([status, n]) => (
                <div key={status}>
                  <div className="row between"><span className="muted small">{status.replace(/_/g, " ")}</span><strong className="small">{n}</strong></div>
                  <div className="progress"><div className="bar ok" style={{ width: `${(n / recent.length) * 100}%` }} /></div>
                </div>
              ))}
              {!recent.length && <EmptyState icon="chart" title="No runs yet" text="Launch an idea from the AI Agent Studio." />}
              <p className="muted small">Counted across the same recent runs, so a long history is only partly visible here.</p>
              <Link className="btn ghost small" to="/projects"><Icon name="folder" size={14} /> All projects</Link>
            </section>
          </div>
        </>
      )}

      <RunPicker runId={runId} onPick={setRunId} note="One run in detail - what it published and what it spent." />
      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}

      {run && (
        <div className="grid2">
          <section className="card stack">
            <div className="row wrap between">
              <h2>{run.idea}</h2>
              <StatusPill status={run.status} />
            </div>
            <div className="row wrap">
              <span className="pill">{run.tokens_used.toLocaleString()} tokens</span>
              <span className="pill">{run.steps} step(s)</span>
              <span className="pill">{s.revisions || 0} edit(s)</span>
              <span className="pill">page v{s.html_version || 0}</span>
              {s.readiness?.total != null && <span className={`pill ${TONE_OF(s.readiness.total)}`}>readiness {s.readiness.total}/100</span>}
            </div>
            <div className="set-rows">
              <div className="set-row"><span className="set-key">Workspace weight</span>
                <strong className="set-val">{(fileBytes / 1024).toFixed(1)} KB across {(s.files || []).length} file(s)</strong></div>
              <div className="set-row"><span className="set-key">Page builds kept</span>
                <strong className="set-val">{(s.versions || []).length}</strong></div>
              <div className="set-row"><span className="set-key">Workspace snapshots</span>
                <strong className="set-val">{(s.workspace_versions || []).length}</strong></div>
              <div className="set-row"><span className="set-key">Change plans</span>
                <strong className="set-val">{(s.change_plans || []).length}</strong></div>
              <div className="set-row"><span className="set-key">Critic reviews</span>
                <strong className="set-val">{(s.critic_history || []).length}</strong></div>
              <div className="set-row"><span className="set-key">Conversation messages</span>
                <strong className="set-val">{(s.chat || []).length}</strong></div>
              <div className="set-row"><span className="set-key">Created</span>
                <strong className="set-val">{fmtDate(run.created_at)}</strong></div>
            </div>
          </section>

          <section className="card stack">
            <h2>Line movement of the last change</h2>
            {s.changed_files ? (
              <>
                <div className="row wrap">
                  <span className="pill add">+{s.changed_files.lines_added}</span>
                  <span className="pill del">-{s.changed_files.lines_removed}</span>
                  <span className="pill">{(s.changed_files.files || []).length} file(s) measured</span>
                  {(s.changed_files.changed || []).map((n) => <span key={n} className="pill mono">{n}</span>)}
                </div>
                <ul className="file-list">
                  {(s.changed_files.files || []).map((f) => (
                    <li key={f.file} className="file-item">
                      <div className="row wrap between">
                        <span className="file-name mono">{f.file}</span>
                        <div className="row wrap">
                          <span className={`pill ${f.status === "changed" ? "" : "warn"}`}>{f.status}</span>
                          <span className="pill">{Math.round(f.bytes_after / 1024)} KB</span>
                          <span className="pill add">+{f.lines_added}</span>
                          <span className="pill del">-{f.lines_removed}</span>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            ) : <p className="muted small">Nothing has been measured against a previous build on this run yet. Any edit,
              patch or restore fills this in.</p>}
            {s.impact && (
              <div className="row wrap">
                <span className="pill">last impact: {s.impact.scope}</span>
                <span className={`pill ${s.impact.counts?.errors ? "err" : "ok"}`}>{s.impact.counts?.errors || 0} blocking risk(s)</span>
                <span className="pill">{s.impact.counts?.warnings || 0} warning(s)</span>
                <Link className="btn ghost small" to="/workspace"><Icon name="code" size={14} /> Measure a change</Link>
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
