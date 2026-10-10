import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ApproveDeploy from "../components/ApproveDeploy";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import PreviewFrame from "../components/PreviewFrame";
import RunPicker, { useRunPick } from "../components/RunPicker";
import SocialPosts from "../components/SocialPosts";
import StatusPill from "../components/StatusPill";
import Tabs from "../components/Tabs";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";
import { copyText, fmtDate, timeAgo } from "../utils";

const sameOriginLink = (token) => `${window.location.origin}/p/${token}`;

/** Where every run stands on its way to the internet, and the two controls that move it forward. */
export default function Deployments() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [stats, setStats] = useState(null);
  const [html, setHtml] = useState("");
  const [tab, setTab] = useState("ship");
  const [busy, setBusy] = useState("");

  const s = run?.state || {};
  const shared = !!run?.share_token;
  const url = shared ? sameOriginLink(run.share_token) : "";
  const version = s.html_version || 0;

  useEffect(() => { api.stats().then(setStats).catch(() => setStats(null)); }, []);

  useEffect(() => {
    setHtml("");
    if (!runId || !version) return;
    let live = true;
    api.getHtml(runId).then((h) => live && setHtml(h)).catch(() => live && setHtml(""));
    return () => { live = false; };
  }, [runId, version]);

  const share = async () => {
    setBusy("share");
    try {
      const r = await api.share(runId);
      setRun({ ...run, share_token: r.token });
      toast("Preview link created", "success");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };
  const unshare = async () => {
    setBusy("share");
    try {
      await api.unshare(runId);
      setRun({ ...run, share_token: null });
      toast("Link revoked - the old URL no longer works", "info");
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };
  const copy = async () => {
    const ok = await copyText(url);
    toast(ok ? "Link copied" : "Could not copy; select the link and copy it manually", ok ? "success" : "error");
  };

  const tabs = [
    { id: "ship", label: "This run" },
    { id: "kit", label: "Launch kit", badge: s.social_posts?.length || null },
    { id: "all", label: "All runs", badge: stats?.deployed ?? null },
  ];

  return (
    <>
      <div className="page-head">
        <div><h1>Deployments</h1><p className="muted">Nothing reaches the internet until you approve it.
          A share link is separate: it shows a preview to anyone you choose, without deploying.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId} />

      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}
      {!runId && !err && <EmptyState icon="rocket" title="No run selected" text="Choose a run to deploy or share it." />}

      {run && (
        <>
          <ApproveDeploy run={run} onChange={setRun} />

          <Tabs tabs={tabs} active={tab} onChange={setTab} />

          {tab === "ship" && (
            <div className="grid2">
              <section className="card stack">
                <div className="row wrap between">
                  <h2>Delivery</h2>
                  <StatusPill status={run.status} />
                </div>
                <div className="row wrap">
                  <span className="pill">page v{version}</span>
                  <span className="pill">{(s.files || []).length} file(s)</span>
                  <span className="pill">{s.readiness?.total != null ? `readiness ${s.readiness.total}/100` : "not scored"}</span>
                  <span className="pill">{s.check_summary?.errors ? `${s.check_summary.errors} check error(s)` : "checks clean"}</span>
                  {s.deploy_mock && <span className="pill warn">simulated deploy</span>}
                  {!s.deploy_mock && s.deploy_warning && <span className="pill warn">live check failed</span>}
                </div>

                <div className="set-rows">
                  <div className="set-row"><span className="set-key">Deployed address</span>
                    <strong className="set-val">{s.deploy_url
                      ? <a href={s.deploy_url} target="_blank" rel="noreferrer">{s.deploy_url}</a>
                      : "Not deployed yet"}</strong></div>
                  <div className="set-row"><span className="set-key">Public preview</span>
                    <strong className="set-val">{url
                      ? <a href={url} target="_blank" rel="noreferrer">{url}</a>
                      : "No link created"}</strong></div>
                  <div className="set-row"><span className="set-key">Last updated</span>
                    <strong className="set-val">{run.updated_at ? fmtDate(run.updated_at) : "—"}</strong></div>
                </div>

                <div className="row wrap">
                  {url ? (
                    <>
                      <button className="btn primary small" onClick={copy} disabled={!!busy}><Icon name="link" size={14} /> Copy link</button>
                      <button className="btn ghost small" onClick={unshare} disabled={busy === "share"}>
                        <Icon name="close" size={14} /> Stop sharing
                      </button>
                    </>
                  ) : (
                    <button className="btn primary small" onClick={share} disabled={busy === "share" || !s.html_key}>
                      <Icon name="link" size={14} /> {busy === "share" ? "Creating…" : "Create preview link"}
                    </button>
                  )}
                  <button className="btn ghost small" onClick={refresh} disabled={!version || working}>
                    <Icon name="refresh" size={14} /> Re-check this run
                  </button>
                </div>
                <p className="muted small">A preview link is read-only: visitors see the current page and can leave
                  feedback, which you can turn into a revision from the run page. Deploying is the only thing that
                  publishes the page itself, and it happens only after you approve.</p>
                {s.deploy_mock && (
                  <p className="muted small">This deploy was simulated because the service has no NETLIFY_AUTH_TOKEN.
                    The address, the run and every file behind it are real; only the upload is skipped.</p>
                )}
                {s.deploy_warning && (
                  <p className="muted small">The Launcher opened the live address straight after the deploy, and this
                    is what it found: {s.deploy_warning}</p>
                )}
              </section>

              <PreviewFrame html={html} loading={working || !html} />
            </div>
          )}

          {tab === "kit" && (s.social_posts?.length || s.email ? (
            <div className="stack">
              <SocialPosts posts={s.social_posts} email={s.email} />
              <p className="muted small">Drafted by the Launcher at deploy time from the page that shipped. Editing the
                page does not rewrite the kit - deploy again after a revision if the copy moved.</p>
            </div>
          ) : <EmptyState icon="rocket" title="No launch kit yet"
            text="The kit (three social posts and one email) is drafted when you approve a run for deploy." />)}

          {tab === "all" && (!stats ? <div className="card skeleton" style={{ height: 160 }} /> : (
            <div className="stack">
              <div className="row wrap">
                <span className="pill">{stats.deployed} deployed</span>
                <span className="pill">{stats.runs} run(s)</span>
                <span className="pill">{stats.projects} project(s)</span>
                <span className="pill">{stats.avg_readiness ?? "-"} avg readiness</span>
              </div>
              {!stats.recent_runs.length ? <EmptyState icon="rocket" title="No runs yet" text="Launch an idea and it will appear here." /> : (
                <ul className="file-list">
                  {stats.recent_runs.map((r) => (
                    <li key={r.id} className="file-item">
                      <div className="row wrap between">
                        <div className="run-main">
                          <strong>{r.idea}</strong>
                          <span className="muted small">{timeAgo(r.created_at)}</span>
                        </div>
                        <div className="row wrap">
                          <StatusPill status={r.status} />
                          {r.score != null && <span className="pill">{r.score}/100</span>}
                          <Link className="btn ghost small" to={`/runs/${r.id}`}><Icon name="arrowRight" size={14} /> Open</Link>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted small">The eight most recent runs of your account, as the usage endpoint reports them.
                Deployment addresses live on each run page.</p>
            </div>
          ))}
        </>
      )}
    </>
  );
}
