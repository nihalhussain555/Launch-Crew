import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import { timeAgo } from "../utils";
import EmptyState from "./EmptyState";
import Icon from "./Icon";

const Stars = ({ value }) => (
  <span className="stars-static" role="img" aria-label={`Rated ${value} out of 5`}>
    {[1, 2, 3, 4, 5].map((n) => (
      <Icon key={n} name={n <= value ? "starFilled" : "star"} size={13} className={n <= value ? "on" : "off"} />
    ))}
  </span>
);

/** Stakeholder feedback collected from the public preview link; selected items become one AI revision. */
export default function FeedbackInbox({ run, items, onShare, onChange, onRefresh }) {
  const toast = useToast();
  const [sel, setSel] = useState(new Set());
  const [target, setTarget] = useState("page");
  const [busy, setBusy] = useState(false);

  if (!run.share_token) {
    return <EmptyState icon="link" title="Collect feedback from other people"
      text="Share a preview link. Visitors can rate the page and leave comments, and you can turn it into a revision."
      action={<button className="btn primary" onClick={onShare}>Create share link</button>} />;
  }
  const pending = items.filter((f) => !f.applied);
  const toggle = (id) => setSel((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const canApply = run.status === "awaiting_approval" && pending.length > 0;

  const apply = async () => {
    setBusy(true);
    try {
      const ids = sel.size ? [...sel] : pending.slice(0, 8).map((f) => f.id);
      onChange(await api.applyFeedback(run.id, ids, target));
      setSel(new Set());
      toast("Applying feedback…", "info");
      onRefresh();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div className="card">
      <div className="row between wrap">
        <div><h2>Feedback inbox</h2><p className="muted small">{items.length} message(s), {pending.length} pending</p></div>
        <div className="row"><button className="btn ghost small" onClick={onRefresh}><Icon name="refresh" size={15} /> Refresh</button>
          <button className="btn ghost small" onClick={onShare}><Icon name="link" size={15} /> Share settings</button></div>
      </div>
      {items.length === 0 && <p className="muted">Nothing yet. Send the link to someone and their feedback will appear here.</p>}
      <ul className="feedback-list">
        {items.map((f) => (
          <li key={f.id} className={f.applied ? "applied" : ""}>
            <input type="checkbox" disabled={f.applied} checked={sel.has(f.id)} onChange={() => toggle(f.id)} aria-label={`Select feedback from ${f.name || "anonymous"}`} />
            <div>
              <div className="row wrap"><strong>{f.name || "Anonymous"}</strong>{f.rating && <Stars value={f.rating} />}
                <span className="muted small">{timeAgo(f.created_at)}</span>{f.applied && <span className="pill ok">Applied</span>}</div>
              <p>{f.message}</p>
            </div>
          </li>
        ))}
      </ul>
      {pending.length > 0 && (
        <div className="row wrap">
          <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="What should change">
            <option value="page">Layout / page</option><option value="copy">Copy / wording</option><option value="design">Colors / fonts</option>
          </select>
          <button className="btn primary" disabled={!canApply || busy} onClick={apply}>
            <Icon name="sparkle" size={16} /> Turn {sel.size ? `${sel.size} selected` : "pending"} into a revision
          </button>
          {!canApply && <span className="muted small">Available while awaiting approval.</span>}
        </div>
      )}
    </div>
  );
}