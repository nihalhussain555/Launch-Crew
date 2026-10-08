import EmptyState from "./EmptyState";
import Icon from "./Icon";
import Modal from "./Modal";

/** Read-only view of the critic loop: what each review found, who it was routed to, what the rebuild produced. */
export default function HealModal({ open, onClose, run }) {
  const s = run.state || {};
  const history = s.critic_history || [];
  const last = history[history.length - 1];

  return (
    <Modal open={open} onClose={onClose} title="Self-healing log" size="md"
      footer={<button className="btn ghost" onClick={onClose}>Close</button>}>
      <p className="muted small">
        After every build the Critic reviews the page in a real browser. Errors are turned into prioritised fixes,
        routed to the agent that owns them and rebuilt - then reviewed again. The loop stops on the first clean
        review or when the crew reaches its review cap.
      </p>
      <div className="row wrap">
        <span className="pill">{history.length} review(s)</span>
        <span className="pill">{s.revisions || 0} AI edit(s)</span>
        <span className="pill">page v{s.html_version || 0}</span>
        {last && <span className={`pill ${last.errors_before ? "err" : "ok"}`}>last review: {last.errors_before || 0} error(s)</span>}
      </div>

      {!history.length && (
        <EmptyState icon="refresh" title="No reviews yet" text="The self-heal loop starts as soon as the Engineer publishes the first build." />
      )}
      <ul className="heal-list">
        {history.map((h, i) => (
          <li key={i} className={`heal-item ${h.errors_before ? "" : "clean"}`}>
            <div className="heal-head">
              <span className="pill">Review {h.iteration}</span>
              <strong className="small">{h.message}</strong>
            </div>
            <div className="muted small">
              Found {h.errors_before || 0} error(s), {h.summary?.warnings || 0} warning(s) at v{h.html_version}.
            </div>
            {!!h.routed && Object.keys(h.routed).length > 0 && (
              <div className="row wrap">
                {Object.entries(h.routed).map(([agent, n]) => (
                  <span key={agent} className="pill"><Icon name="cpu" size={12} /> {agent} × {n}</span>
                ))}
              </div>
            )}
            {!!h.fixes?.length && (
              <ul className="tips">
                {h.fixes.map((f, j) => <li key={j} className="small"><span className="pill">{f.agent}</span> {f.instruction}</li>)}
              </ul>
            )}
            {!h.errors_before && !h.fixes?.length && <div className="muted small">Nothing to repair - the page moved on unchanged.</div>}
          </li>
        ))}
      </ul>
    </Modal>
  );
}
