import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import AgentTrace from "../components/AgentTrace";
import ApproveDeploy from "../components/ApproveDeploy";
import CriticReport from "../components/CriticReport";
import PreviewFrame from "../components/PreviewFrame";
import SocialPosts from "../components/SocialPosts";
import { useRunStream } from "../hooks/useRunStream";
import ReviseForm from "../components/ReviseForm";

const REFRESH_ON = new Set(["agent_message", "check_results", "awaiting_approval", "deployed", "failed"]);

export default function RunDetail() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [err, setErr] = useState("");
  const [html, setHtml] = useState("");
  const [shots, setShots] = useState({});
  const timer = useRef();
  const version = useRef(0);

  const refresh = useCallback(async () => {
    try { setRun(await api.getRun(runId)); setErr(""); } catch (e) { setErr(e.message); }
  }, [runId]);

  useEffect(() => { setRun(null); refresh(); }, [refresh]);

  // Debounced refetch whenever something meaningful happens on the stream.
  const { events, connected } = useRunStream(runId, (ev) => {
    if (!REFRESH_ON.has(ev.type)) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(refresh, 250);
  });

  // Reload the preview when a new page version exists.
  const v = run?.state?.html_version || 0;
  useEffect(() => {
    if (!v || v === version.current) return;
    version.current = v;
    api.getHtml(runId).then(setHtml).catch(() => {});
  }, [v, runId]);

  // Screenshots are (re)written by every Critic review, so key off the review counter.
  const shotKeys = run?.state?.screenshot_keys || {};
  const shotTag = `${run?.state?.iteration || 0}:${Object.keys(shotKeys).join(",")}`;
  useEffect(() => {
    Object.keys(shotKeys).forEach((vp) =>
      api.screenshotUrl(runId, vp)
        .then((u) => setShots((p) => { if (p[vp]) URL.revokeObjectURL(p[vp]); return { ...p, [vp]: u }; }))
        .catch(() => {}));
  }, [shotTag, runId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => Object.values(shots).forEach(URL.revokeObjectURL), []); // eslint-disable-line

  if (err && !run) return <div className="error" role="alert">{err} <Link to="/">Back</Link></div>;
  if (!run) return <div className="center muted">Loading run…</div>;
  const s = run.state || {};

  return (
    <>
      <div className="row between wrap">
        <div><Link to="/" className="muted small">← All projects</Link><h1>{run.idea}</h1></div>
        <div className="row"><span className={`pill ${run.status === "failed" ? "err" : run.status === "deployed" ? "ok" : "warn"}`}>{run.status.replace("_", " ")}</span>
          <span className="muted small">{run.tokens_used.toLocaleString()} tokens · {run.steps} steps</span></div>
      </div>
      {err && <div className="error" role="alert">{err}</div>}
      <ApproveDeploy run={run} onChange={setRun} />
        <ReviseForm run={run} onChange={setRun} />
      <div className="grid2">
        <AgentTrace events={events} connected={connected} status={run.status} />
        <PreviewFrame html={html} loading={["queued", "running"].includes(run.status)} />
      </div>
      <CriticReport state={s} shots={shots} />
      <SocialPosts posts={s.social_posts} email={s.email} />
    </>
  );
}
