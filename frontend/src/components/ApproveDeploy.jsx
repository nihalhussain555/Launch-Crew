import { useState } from "react";
import { api } from "../api";
import { useToast } from "../toast";
import ConfirmModal from "./ConfirmModal";
import Icon from "./Icon";

export default function ApproveDeploy({ run, onChange }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const s = run.state || {};
  const errors = s.check_summary?.errors || 0;

  const approve = async () => {
    try { onChange(await api.approve(run.id)); toast("Deploying…", "info"); }
    catch (e) { toast(e.message, "error"); }
    setOpen(false);
  };

  if (run.status === "awaiting_approval")
    return (
      <section className="card highlight">
        <div className="row between wrap">
          <div><h2>Ready to deploy?</h2><p className="muted">Nothing is published until you approve.{errors > 0 && <strong> {errors} check error(s) remain.</strong>}</p></div>
          <button className="btn primary big" onClick={() => setOpen(true)}>Approve &amp; deploy</button>
        </div>
        <ConfirmModal open={open} onClose={() => setOpen(false)} onConfirm={approve} confirmLabel="Yes, deploy"
          title="Deploy this page?" message="The page will be published and the launch kit (3 social posts + 1 email) will be drafted.">
          <ul className="tips">
            {s.readiness && <li>Readiness score: <strong>{s.readiness.total}/100</strong> ({s.readiness.verdict})</li>}
            <li>{errors ? `${errors} browser check error(s) are still open` : "All required browser checks passed"}</li>
            {s.revisions > 0 && <li>{s.revisions} revision(s) applied</li>}
          </ul>
        </ConfirmModal>
      </section>
    );
  if (run.status === "deploying") return <section className="card highlight"><h2>Deploying…</h2><p className="muted">Publishing the page and drafting your launch kit.</p></section>;
  if (run.status === "deployed")
    return (
      <section className="card highlight">
        <h2><Icon name="rocket" size={19} /> Live</h2>
        <p><a href={s.deploy_url} target="_blank" rel="noreferrer">{s.deploy_url}</a></p>
        {s.deploy_mock && <p className="muted small">Simulated deploy. Set NETLIFY_AUTH_TOKEN on the backend to publish for real.</p>}
      </section>
    );
  if (run.status === "failed") return <section className="card"><div className="error" role="alert"><strong>Run failed.</strong> {run.error}</div></section>;
  return null;
}