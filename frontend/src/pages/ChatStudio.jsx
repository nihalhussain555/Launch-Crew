import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import PreviewFrame from "../components/PreviewFrame";
import RunPicker, { useRunPick } from "../components/RunPicker";
import StatusPill from "../components/StatusPill";
import { useRun } from "../hooks/useRun";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const TARGET_LABEL = { page: "layout", copy: "wording", design: "styling", files: "file patch" };

/** Requests are plain words; the orchestrator routes each to the agent that owns the change. */
const SUGGESTIONS = [
  "Make the headline shorter and punchier",
  "Add more spacing between the sections",
  "Turn the primary button into a dark outline",
  "Add a FAQ section about pricing",
];

export default function ChatStudio() {
  const { runId, setRunId } = useRunPick();
  const { run, setRun, err, refresh, working } = useRun(runId);
  const toast = useToast();
  const [text, setText] = useState("");
  const [pending, setPending] = useState("");
  const [busy, setBusy] = useState(false);
  const [html, setHtml] = useState("");
  const logRef = useRef(null);
  const loadedFor = useRef(0);

  const s = run?.state || {};
  const thread = s.chat || [];
  const editable = run?.status === "awaiting_approval";
  const version = s.html_version || 0;

  useEffect(() => { setHtml(""); setPending(""); loadedFor.current = 0; }, [runId]);
  useEffect(() => {
    if (!version || version === loadedFor.current) return;
    loadedFor.current = version;
    api.getHtml(runId).then(setHtml).catch(() => setHtml(""));
  }, [version, runId]);
  useEffect(() => { logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [thread.length, pending]);
  useEffect(() => { if (!working) setPending(""); }, [working]);

  const send = async (e) => {
    e.preventDefault();
    const msg = text.trim();
    if (msg.length < 3) return;
    setBusy(true);
    try {
      setRun(await api.chat(runId, msg));
      setPending(msg); setText("");
      await refresh();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(false); }
  };

  const debugPass = async () => {
    setBusy(true);
    try {
      setRun(await api.debug(runId));
      toast("Debug pass queued — the crew is re-checking the page", "success");
      await refresh();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>AI Chat</h1><p className="muted">Ask for a change in your own words. The crew rebuilds the page,
          re-runs the browser checks and returns it here for approval.</p></div>
        {run && <Link className="btn ghost" to={`/runs/${run.id}`}><Icon name="eye" size={15} /> Run page</Link>}
      </div>
      <RunPicker runId={runId} onPick={setRunId}
        note="Every message costs one of this run’s edits, the same as a revision." />

      {err && !run && <ErrorState title="Run not available" message={err} retry={refresh} />}
      {!run && !err && !runId && <EmptyState icon="chat" title="No run selected" text="Pick a run to talk to its crew." />}

      {run && (
        <div className="grid2">
          <section className="card stack">
            <div className="row wrap between">
              <h2>Conversation</h2>
              <div className="row wrap">
                <StatusPill status={run.status} />
                <span className="pill">page v{version}</span>
                <span className="pill">{s.revisions || 0} edit(s)</span>
              </div>
            </div>

            <div className="chat-log chat-page-log" ref={logRef} aria-live="polite">
              {!thread.length && !pending && (
                <p className="muted small">Nothing said yet. Try one of the suggestions below - the wording goes to the
                  Copywriter, styling to the Designer, layout to the Engineer.</p>
              )}
              {thread.map((m, i) => (
                <div key={i} className={`chat-msg ${m.role}`}>
                  <div className="chat-who">
                    <Icon name={m.role === "user" ? "user" : "cpu"} size={13} />
                    <span>{m.role === "user" ? "You" : "Crew"}</span>
                    {m.target && <span className="pill">{TARGET_LABEL[m.target] || m.target}</span>}
                    {m.version && <span className="pill">v{m.version}</span>}
                    {m.at && <span className="muted small">{timeAgo(m.at)}</span>}
                  </div>
                  <p>{m.text}</p>
                </div>
              ))}
              {pending && (
                <div className="chat-msg user pending">
                  <div className="chat-who"><Icon name="user" size={13} /><span>You</span></div>
                  <p>{pending}</p>
                </div>
              )}
              {working && (
                <div className="chat-msg crew">
                  <div className="chat-who"><Icon name="cpu" size={13} /><span>Crew</span>
                    <span className="pill warn"><span className="dot live" aria-hidden="true" /> working</span></div>
                  <p>Rebuilding and re-checking the page…</p>
                </div>
              )}
            </div>

            <form className="stack" onSubmit={send}>
              <label>Your change
                <textarea rows={3} value={text} maxLength={500} aria-label="Message to the crew"
                  disabled={busy || working || !editable} onChange={(e) => setText(e.target.value)}
                  placeholder="e.g. Make the headline shorter and move the pricing table above the FAQ" />
              </label>
              <div className="row wrap">
                <button className="btn primary" disabled={busy || working || !editable || text.trim().length < 3}>
                  <Icon name="sparkle" size={15} /> {busy ? "Sending…" : "Send to the crew"}
                </button>
                <button type="button" className="btn ghost" onClick={debugPass} disabled={busy || working || !editable}>
                  <Icon name="cpu" size={15} /> Ask the crew to debug
                </button>
              </div>
            </form>

            {editable && (
              <div className="row wrap">
                {SUGGESTIONS.map((g) => (
                  <button key={g} className="chip" disabled={busy || working} onClick={() => setText(g)}>{g}</button>
                ))}
              </div>
            )}
            {!editable && !working && (
              <p className="muted small">Chat edits are available while the run awaits approval.
                {run.status === "deployed" ? " This run is already deployed." : ""}</p>
            )}
            <p className="muted small">Prefer to name the exact file and fragment? Use
              <Link to="/workspace"> Code Workspace</Link> - it measures the impact before writing anything.</p>
          </section>

          <PreviewFrame html={html} loading={working || !html} />
        </div>
      )}
    </>
  );
}
