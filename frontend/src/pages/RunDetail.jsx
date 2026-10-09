import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import AgentTrace from "../components/AgentTrace";
import ApproveDeploy from "../components/ApproveDeploy";
import AudiencePanel from "../components/AudiencePanel";
import AuditModal from "../components/AuditModal";
import ChatEditModal from "../components/ChatEditModal";
import CriticReport from "../components/CriticReport";
import DebugModal from "../components/DebugModal";
import DiffModal from "../components/DiffModal";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import FeedbackInbox from "../components/FeedbackInbox";
import FilesModal from "../components/FilesModal";
import HealModal from "../components/HealModal";
import HistoryModal from "../components/HistoryModal";
import Icon from "../components/Icon";
import PreviewFrame from "../components/PreviewFrame";
import ReadinessModal from "../components/ReadinessModal";
import ReviseForm from "../components/ReviseForm";
import ScoreRing from "../components/ScoreRing";
import ShareModal from "../components/ShareModal";
import SocialPosts from "../components/SocialPosts";
import StatusPill from "../components/StatusPill";
import Tabs from "../components/Tabs";
import WorkspaceModal from "../components/WorkspaceModal";
import { useRunStream } from "../hooks/useRunStream";

const REFRESH_ON = new Set(["agent_message", "audit_report", "check_results", "awaiting_approval", "workspace_updated", "deployed", "failed"]);

/** Workspace tools: every run is a set of files, a version history and a conversation. */
const TOOLS = [
  { id: "files", icon: "layers", label: "Files" },
  { id: "history", icon: "book", label: "History" },
  { id: "diff", icon: "arrowRight", label: "Compare" },
  { id: "chat", icon: "sparkle", label: "AI edit" },
  { id: "debug", icon: "cpu", label: "Debug" },
  { id: "heal", icon: "refresh", label: "Self-heal" },
  { id: "audits", icon: "audit", label: "Audits" },
  { id: "workspace", icon: "folder", label: "Project" },
];

export default function RunDetail() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [err, setErr] = useState("");
  const [html, setHtml] = useState("");
  const [shots, setShots] = useState({});
  const [feedback, setFeedback] = useState([]);
  const [tab, setTab] = useState("overview");
  const [shareOpen, setShareOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  const [tool, setTool] = useState("");
  const [diffRange, setDiffRange] = useState(null);
  const timer = useRef();
  const version = useRef(0);

  const refresh = useCallback(async () => {
    try { setRun(await api.getRun(runId)); setErr(""); } catch (e) { setErr(e.message); }
  }, [runId]);

  useEffect(() => {
    setRun(null); setHtml(""); setShots({}); setFeedback([]); setTab("overview"); setTool(""); setDiffRange(null); version.current = 0;
    refresh();
  }, [refresh]);

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

  // Feedback inbox (only exists once the run is shared); light polling.
  const shared = !!run?.share_token;
  const loadFeedback = useCallback(async () => { try { setFeedback(await api.feedback(runId)); } catch { /* ignore */ } }, [runId]);
  useEffect(() => {
    if (!shared) { setFeedback([]); return undefined; }
    loadFeedback();
    const t = setInterval(loadFeedback, 20000);
    return () => clearInterval(t);
  }, [shared, loadFeedback]);

  useEffect(() => { if (run?.status === "deployed" && run.state?.social_posts?.length) setTab("launch"); }, [run?.status]); // eslint-disable-line

  if (err && !run) return <ErrorState title="Run not available" message={err} back="/projects" backLabel="Back to projects" retry={refresh} />;
  if (!run) return <div className="card skeleton" style={{ height: 260 }} />;
  const s = run.state || {};
  const pending = feedback.filter((f) => !f.applied).length;
  const errors = s.check_summary?.errors || 0;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "audience", label: "Audience", badge: s.panel ? s.panel.avg_score : null },
    { id: "feedback", label: "Feedback", badge: pending || null, tone: "warn" },
    { id: "quality", label: "Quality", badge: errors || null, tone: "err" },
    ...(s.social_posts?.length ? [{ id: "launch", label: "Launch kit" }] : []),
  ];

  const openTool = (id) => {
    if (id === "diff" && !diffRange && s.html_version > 1) setDiffRange({ from: s.html_version - 1, to: s.html_version });
    setTool(id);
  };
  const closeTool = () => setTool("");
  const compare = (from, to) => { setDiffRange({ from, to }); setTool("diff"); };

  return (
    <>
      <div className="page-head">
        <div>
          <Link to={run.project_id ? `/projects/${run.project_id}` : "/projects"} className="muted small"><Icon name="left" size={13} /> Project</Link>
          <h1>{run.idea}</h1>
          <div className="row wrap"><StatusPill status={run.status} />
            <span className="muted small">{run.tokens_used.toLocaleString()} tokens · {run.steps} steps{s.revisions ? ` · ${s.revisions} revision(s)` : ""}</span></div>
        </div>
        <div className="row">
          {s.readiness && <ScoreRing value={s.readiness.total} size={72} stroke={8} onClick={() => setScoreOpen(true)} label="How is this scored?" />}
          <button className="btn" disabled={!s.html_key} onClick={() => setShareOpen(true)}><Icon name="link" size={16} /> {shared ? "Shared" : "Share"}</button>
        </div>
      </div>
      {err && <div className="error" role="alert">{err}</div>}

      <div className="ws-bar">
        {TOOLS.map((t) => (
          <button key={t.id} className={`btn ghost small ${tool === t.id ? "on" : ""}`} onClick={() => openTool(t.id)}>
            <Icon name={t.icon} size={15} /> {t.label}
          </button>
        ))}
      </div>

      <ApproveDeploy run={run} onChange={setRun} />
      <ReviseForm run={run} onChange={setRun} />

      <Tabs tabs={tabs} active={tab} onChange={setTab} />
      {tab === "overview" && (
        <div className="grid2">
          <AgentTrace events={events} connected={connected} status={run.status} />
          <PreviewFrame html={html} loading={["queued", "running"].includes(run.status)} />
        </div>
      )}
      {tab === "audience" && <AudiencePanel run={run} onChange={setRun} />}
      {tab === "feedback" && <FeedbackInbox run={run} items={feedback} onShare={() => setShareOpen(true)} onChange={setRun} onRefresh={loadFeedback} />}
      {tab === "quality" && (s.check_results?.length
        ? <CriticReport state={s} shots={shots} />
        : <EmptyState icon="shield" title="No quality report yet" text="Browser checks run once the page is built." />)}
      {tab === "launch" && <SocialPosts posts={s.social_posts} email={s.email} />}

      <ShareModal open={shareOpen} onClose={() => setShareOpen(false)} run={run} onChange={setRun} />
      <ReadinessModal open={scoreOpen} onClose={() => setScoreOpen(false)} state={s} />

      <FilesModal open={tool === "files"} onClose={closeTool} run={run} />
      <HistoryModal open={tool === "history"} onClose={closeTool} run={run} onChange={setRun} onDiff={compare} />
      <DiffModal open={tool === "diff"} onClose={closeTool} run={run} range={diffRange} setRange={setDiffRange} />
      <ChatEditModal open={tool === "chat"} onClose={closeTool} run={run} onChange={setRun} />
      <DebugModal open={tool === "debug"} onClose={closeTool} run={run} onChange={setRun} />
      <HealModal open={tool === "heal"} onClose={closeTool} run={run} />
      <AuditModal open={tool === "audits"} onClose={closeTool} run={run} onChange={setRun} />
      <WorkspaceModal open={tool === "workspace"} onClose={closeTool} run={run} />
    </>
  );
}