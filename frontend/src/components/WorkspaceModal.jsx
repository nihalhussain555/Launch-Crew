import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { timeAgo } from "../utils";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import Modal from "./Modal";
import StatusPill from "./StatusPill";

/** Everything this project has produced: every run, its status, score and cost, in one place. */
export default function WorkspaceModal({ open, onClose, run }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");

  const load = () => {
    setErr(""); setData(null);
    api.getProject(run.project_id).then(setData).catch((e) => setErr(e.message));
  };
  useEffect(() => {
    if (!open) { setData(null); setErr(""); return; }
    load();
  }, [open, run.project_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const goto = (id) => { onClose(); if (id !== run.id) navigate(`/runs/${id}`); };
  const runs = data?.runs || [];

  return (
    <Modal open={open} onClose={onClose} title="Project workspace" size="md"
      footer={<button className="btn ghost" onClick={onClose}>Close</button>}>
      {err && <ErrorState title="Couldn’t load the workspace" message={err} retry={load} />}
      {!data && !err && <div className="card skeleton" style={{ height: 140 }} />}
      {data && (
        <>
          <p className="muted small">
            {runs.length} run(s) for “{data.idea}”. Each run gets its own design direction, files, versions and history.
          </p>
          <ul className="ws-list">
            {runs.map((r) => (
              <li key={r.id} className={`ws-item ${r.id === run.id ? "current" : ""}`}>
                <div className="row wrap between">
                  <div className="ws-main">
                    <strong>{r.idea}</strong>
                    <div className="row wrap">
                      <StatusPill status={r.status} />
                      {r.score != null && <span className="pill">{r.score}/100</span>}
                      <span className="muted small">{r.tokens_used.toLocaleString()} tokens · {timeAgo(r.created_at)}</span>
                    </div>
                  </div>
                  <button className="btn ghost small" onClick={() => goto(r.id)} disabled={r.id === run.id}>
                    <Icon name={r.id === run.id ? "check" : "arrowRight"} size={14} />
                    {r.id === run.id ? "This run" : "Open"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {runs.length === 1 && (
            <p className="muted small">Start another run from the project page to compare a different direction side by side.</p>
          )}
        </>
      )}
    </Modal>
  );
}
