import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { timeAgo } from "../utils";
import Icon from "./Icon";
import Modal from "./Modal";

const TARGET_LABEL = { page: "layout", copy: "wording", design: "styling" };

/** Conversational editing: say what to change in plain words, the crew routes it to the owning agent. */
export default function ChatEditModal({ open, onClose, run, onChange }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState("");   // shown until the server writes it into the thread
  const logRef = useRef(null);

  const thread = run.state?.chat || [];
  const editable = run.status === "awaiting_approval";
  const working = run.status === "running" || run.status === "queued";

  useEffect(() => { if (open) logRef.current?.scrollTo({ top: logRef.current.scrollHeight }); }, [open, thread.length]);
  useEffect(() => { if (!open) { setText(""); setErr(""); setPending(""); } }, [open]);
  useEffect(() => { if (!working) setPending(""); }, [working]);

  const send = async (e) => {
    e.preventDefault();
    const msg = text.trim();
    if (msg.length < 3) return;
    setBusy(true); setErr("");
    try {
      onChange(await api.chat(run.id, msg));
      setPending(msg); setText("");
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title="Talk to the crew" size="md"
      footer={<>
        <button className="btn ghost" onClick={onClose}>Close</button>
        <button className="btn primary" onClick={send} disabled={busy || working || !editable || text.trim().length < 3}>
          <Icon name="sparkle" size={15} /> {busy ? "Sending…" : "Send"}
        </button>
      </>}>
      <p className="muted small">
        Every message rebuilds the page, re-runs the browser checks and returns it here for approval -
        the same pipeline the crew runs on its own.
      </p>

      <div className="chat-log" ref={logRef} aria-live="polite">
        {!thread.length && !pending && (
          <p className="muted small">No edits yet. Try “Make the headline shorter and the call-to-action button larger”.</p>
        )}
        {thread.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <div className="chat-who">
              <Icon name={m.role === "user" ? "user" : "cpu"} size={13} />
              <span>{m.role === "user" ? "You" : "Crew"}</span>
              {m.target && <span className="pill">{TARGET_LABEL[m.target] || m.target}</span>}
              {m.version && <span className="pill">v{m.version}</span>}
              <span className="muted small">{timeAgo(m.at)}</span>
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

      {err && <div className="error" role="alert">{err}</div>}
      {!editable && !working && (
        <p className="muted small">Chat edits are available while the run awaits approval.</p>
      )}
      <form className="chat-form" onSubmit={send}>
        <textarea rows={2} required minLength={3} maxLength={500} value={text} disabled={busy || working || !editable}
          onChange={(e) => setText(e.target.value)} placeholder="Describe the change you want…" aria-label="Message to the crew" />
      </form>
    </Modal>
  );
}
