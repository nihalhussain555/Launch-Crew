import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import RunPicker, { useRunPick } from "../components/RunPicker";
import ScoreRing from "../components/ScoreRing";
import StatusPill from "../components/StatusPill";
import { PIPELINE } from "../constants";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";

/** Which stage of the pipeline a run's status puts it at. `awaiting_approval` is the human gate. */
const STAGE_OF_STATUS = { queued: 0, running: 4, awaiting_approval: 7, deploying: 8, deployed: 8, failed: 4 };

/** Every way back into the pipeline, and the endpoint each one calls. */
const ENTRIES = [
  { to: "/chat", icon: "chat", label: "Say what to change",
    text: "A plain-language message is routed to the agent that owns it - wording to the Copywriter, styling to the "
        + "Designer, layout to the Engineer - then the page rebuilds and re-checks.",
    endpoint: "POST /api/runs/{id}/chat" },
  { to: "/workspace", icon: "code", label: "Patch the files yourself",
    text: "Name the file, the operation and the exact fragment. The workspace is indexed and the impact measured "
        + "before anything is written; the patched page still goes through the sanitizer and the browser checks.",
    endpoint: "POST /api/runs/{id}/workspace/apply" },
  { to: "/quality", icon: "shield", label: "Audit, then repair",
    text: "Six deterministic scanners measure the live page and stamp each report with the version it measured. "
        + "Repairing applies their instructions through the same routed-fix path the critic loop uses.",
    endpoint: "POST /api/runs/{id}/audit/repair" },
  { to: "/versions", icon: "layers", label: "Roll anything back",
    text: "A page build restores the document; a workspace snapshot restores the whole file set. Both are recomputed "
        + "through the checks afterwards, so a rollback is measured, not assumed.",
    endpoint: "POST /api/runs/{id}/workspace/restore" },
];

/** The workflow the crew actually runs, and where this run sits in it right now. */
export default function Workflows() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [busy, setBusy] = useState("");

  const s = run?.state || {};
  const has = {
    brief: !!s.brief, strategy: !!s.strategy, content: !!s.content, design: !!s.design,
    html: !!s.html_key, check_results: (s.check_results || []).length > 0, panel: !!s.panel,
    readiness: !!s.readiness, deploy_url: !!s.deploy_url,
  };
  const at = run ? STAGE_OF_STATUS[run.status] ?? 0 : -1;
  const history = s.critic_history || [];
  const last = history[history.length - 1];
  const errors = s.check_summary?.errors || 0;

  const debugPass = async () => {
    setBusy("debug");
    try {
      setRun(await api.debug(runId));
      toast("Debug pass queued — checks re-running", "success");
      await refresh();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Agent Workflows</h1><p className="muted">The crew is an explicit pipeline, not one model with a long prompt.
          This is the order it runs in and where a run sits in it.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId}
        note="Pick a run to follow its pipeline live; the stage list below is the same for every run." />

      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}

      <section className="card stack">
        <h2>Build pipeline</h2>
        <p className="muted small">Each agent gets one job, one output and the shared run state. A step counter, a token
          budget and a per-agent timeout guard the run, and the critic loop is capped, so a run cannot spin.</p>
        <ol className="stage-list">
          {PIPELINE.map((st, i) => {
            const done = has[st.output];
            return (
              <li key={st.agent} className={`stage ${done ? "done" : ""} ${i === at && run ? "now" : ""}`}>
                <span className="stage-ico"><Icon name={st.icon} size={17} /></span>
                <div className="stage-body">
                  <div className="row wrap">
                    <strong>{st.label}</strong>
                    <span className="pill mono">{st.agent}</span>
                    {done ? <span className="pill ok">produced</span> : <span className="pill">waiting</span>}
                    {i === at && run && <span className="pill warn">here now</span>}
                  </div>
                  <p className="muted small">{st.does}</p>
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {!run ? (
        <EmptyState icon="workflow" title="No run to follow" text="Choose a run above, or start one from the AI Agent Studio."
          action={<Link to="/dashboard" className="btn primary">Launch an idea</Link>} />
      ) : (
        <>
          <section className="card stack">
            <div className="row wrap between">
              <h2>This run</h2>
              <StatusPill status={run.status} />
            </div>
            <div className="row wrap">
              <span className="pill">page v{s.html_version || 0}</span>
              <span className="pill">{run.steps} step(s)</span>
              <span className="pill">{run.tokens_used.toLocaleString()} tokens</span>
              <span className="pill">{s.revisions || 0} edit(s)</span>
              <span className="pill">{(s.files || []).length} file(s)</span>
              <span className="pill">{(s.workspace_versions || []).length} snapshot(s)</span>
              <span className="pill">{(s.change_plans || []).length} change plan(s)</span>
              <span className={`pill ${errors ? "err" : "ok"}`}>{errors} check error(s)</span>
              <span className="pill">{s.check_summary?.warnings || 0} warning(s)</span>
            </div>
            <div className="row wrap">
              {s.readiness?.total != null && <ScoreRing value={s.readiness.total} size={54} stroke={6} />}
              <p className="muted small">{s.readiness ? `Readiness ${s.readiness.total}/100 — ${s.readiness.verdict}. ` : ""}
                Review round {s.iteration || 0} of the critic loop, measured on v{s.html_version || 0}.</p>
            </div>
            {run.status === "awaiting_approval" && (
              <div className="row wrap">
                <button className="btn primary small" onClick={debugPass} disabled={!!busy}>
                  <Icon name="cpu" size={14} /> {busy === "debug" ? "Queueing…" : "Run a debug pass"}
                </button>
                <span className="muted small">Re-runs the browser checks, routes any errors to their agent, rebuilds and reviews again.</span>
              </div>
            )}
          </section>

          <section className="card stack">
            <h2>Self-healing loop</h2>
            <p className="muted small">The Critic drives real Chromium at 1280px and 375px. Errors become prioritised fix
              instructions, routed to the agent that owns them, then the page is rebuilt and reviewed again until a
              review is clean or the cap is reached.</p>
            <div className="row wrap">
              <span className="pill">{history.length} review(s)</span>
              {last && <span className={`pill ${last.errors_before ? "err" : "ok"}`}>last: {last.errors_before || 0} error(s) at v{last.html_version}</span>}
              {last && !!Object.keys(last.routed || {}).length && Object.entries(last.routed).map(([a, n]) => (
                <span key={a} className="pill"><Icon name="cpu" size={12} /> {a} × {n}</span>))}
            </div>
            {history.length ? (
              <ul className="heal-list">
                {history.slice(-4).reverse().map((h, i) => (
                  <li key={history.length - i} className={`heal-item ${h.errors_before ? "" : "clean"}`}>
                    <div className="heal-head"><span className="pill">Review {h.iteration}</span><strong className="small">{h.message}</strong></div>
                    <div className="muted small">v{h.html_version} · {h.errors_before || 0} error(s), {h.summary?.warnings || 0} warning(s)
                      {h.fixes?.length ? ` · ${h.fixes.length} instruction(s) routed` : " · nothing to repair"}</div>
                  </li>
                ))}
              </ul>
            ) : <p className="muted small">No review has run yet — the loop starts after the Engineer publishes the first build.</p>}
            <Link className="btn ghost small" to={`/runs/${run.id}`}><Icon name="book" size={14} /> Full log on the run page</Link>
          </section>

          <section className="card stack">
            <h2>Ways back in</h2>
            <p className="muted small">Every edit re-enters the same guarded pipeline, so nothing reaches the preview
              without passing the sanitizer and the browser checks again.</p>
            <div className="grid-cards">
              {ENTRIES.map((e) => (
                <Link key={e.to} to={e.to} className="card entry-card">
                  <span className="stat-icon"><Icon name={e.icon} size={20} /></span>
                  <strong>{e.label}</strong>
                  <p className="muted small">{e.text}</p>
                  {/* zero-width spaces give the wrap points, so a long path breaks after a "/" instead of mid-word */}
                  <span className="pill mono">{e.endpoint.split("/").join("/\u200B")}</span>
                </Link>
              ))}
            </div>
          </section>
        </>
      )}
    </>
  );
}
