import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import ConfirmModal from "./ConfirmModal";
import EmptyState from "./EmptyState";
import Icon from "./Icon";

const tone = (s) => (s >= 8 ? "ok" : s >= 6 ? "warn" : "err");

/** Simulated audience: synthetic visitors react to the page; one click applies the suggested fix. */
export default function AudiencePanel({ run, onChange }) {
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const p = run.state?.panel;
  if (!p) return <EmptyState icon="user" title="No audience reaction yet" text="The simulated audience reviews the page once it is built." />;
  const canApply = run.status === "awaiting_approval" && p.suggested_fix;

  const apply = async () => {
    try { onChange(await api.revise(run.id, p.suggested_fix, p.suggested_target)); toast("Applying the suggestion…", "info"); }
    catch (e) { toast(e.message, "error"); }
    setConfirm(false);
  };

  return (
    <>
      <div className="card">
        <div className="row between wrap">
          <div><h2>Simulated audience</h2><p className="muted small">Synthetic visitors react to your page before real ones do. Treat it as a fast sanity check, not market research.</p></div>
          <div className="panel-stats">
            <div><strong>{p.avg_score}</strong><span className="muted small">avg / 10</span></div>
            <div><strong>{p.signups}/{p.reactions.length}</strong><span className="muted small">would sign up</span></div>
          </div>
        </div>
        {p.summary && <p>{p.summary}</p>}
      </div>
      <div className="grid-cards">
        {p.reactions.map((r, i) => (
          <article key={i} className="card reaction">
            <div className="row between"><strong>{r.persona}</strong><span className={`pill ${tone(r.score)}`}>{r.score}/10</span></div>
            <p>“{r.first_impression}”</p>
            <div className="objection"><span className="muted small">Biggest objection</span><div>{r.top_objection}</div></div>
            <span className={`small row ${r.would_sign_up ? "ok-text" : "err-text"}`} style={{ gap: 6 }}>
              <Icon name={r.would_sign_up ? "check" : "close"} size={15} />
              {r.would_sign_up ? "Would sign up" : "Would not sign up yet"}
            </span>
          </article>
        ))}
      </div>
      {p.suggested_fix && (
        <div className="card highlight">
          <h3><Icon name="sparkle" size={17} /> Suggested improvement</h3>
          <p>{p.suggested_fix}</p>
          <div className="row"><span className="pill">{p.suggested_target}</span>
            <button className="btn primary" disabled={!canApply} onClick={() => setConfirm(true)}>Apply this suggestion</button></div>
          {!canApply && <span className="muted small">Available while the run is awaiting approval.</span>}
        </div>
      )}
      <ConfirmModal open={confirm} onClose={() => setConfirm(false)} onConfirm={apply} confirmLabel="Apply & rebuild"
        title="Apply this suggestion?" message={`The crew will rebuild the ${p.suggested_target} and re-run the checks: “${p.suggested_fix}”`} />
    </>
  );
}