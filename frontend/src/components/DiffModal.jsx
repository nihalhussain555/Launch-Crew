import { useEffect, useState } from "react";
import { api } from "../api";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import Modal from "./Modal";
import { DiffBody, DiffModeToggle } from "./DiffView";

/** Git-style diff between two saved versions of this run's page. */
export default function DiffModal({ open, onClose, run, range, setRange }) {
  const [versions, setVersions] = useState(null);
  const [data, setData] = useState(null);
  const [mode, setMode] = useState("unified");
  const [err, setErr] = useState("");
  const [again, setAgain] = useState(0);   // bump to re-request the current range

  useEffect(() => {
    if (!open) { setVersions(null); setData(null); setErr(""); return; }
    api.versions(run.id).then((d) => setVersions(d)).catch((e) => setErr(e.message));
  }, [open, run.id]);

  useEffect(() => {
    if (!open || !range || !range.from || !range.to) { setData(null); return undefined; }
    let live = true;
    setData(null); setErr("");
    api.diff(run.id, range.from, range.to).then((d) => { if (live) setData(d); }).catch((e) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, [open, run.id, range?.from, range?.to, again]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (key, value) => setRange({ ...(range || {}), [key]: Number(value) });
  const options = versions?.versions || [];

  return (
    <Modal open={open} onClose={onClose} title="Compare versions" size="lg"
      footer={<button className="btn ghost" onClick={onClose}>Close</button>}>
      <div className="row wrap diff-picks">
        <label className="pick">
          <span className="muted small">From</span>
          <select value={range?.from || ""} onChange={(e) => pick("from", e.target.value)} aria-label="Older version">
            <option value="">Choose…</option>
            {options.map((v) => <option key={v.v} value={v.v}>v{v.v} - {v.note}</option>)}
          </select>
        </label>
        <Icon name="arrowRight" size={16} />
        <label className="pick">
          <span className="muted small">To</span>
          <select value={range?.to || ""} onChange={(e) => pick("to", e.target.value)} aria-label="Newer version">
            <option value="">Choose…</option>
            {options.map((v) => <option key={v.v} value={v.v}>v{v.v} - {v.note}</option>)}
          </select>
        </label>
      </div>

      {err && <ErrorState title="Couldn’t build the diff" message={err} retry={() => setAgain((n) => n + 1)} />}
      {!err && range && range.from === range.to && (
        <EmptyState icon="arrowRight" title="Pick two different versions" text="Compare any build against any other to see exactly what the crew changed." />
      )}
      {!err && (!range || !range.from || !range.to) && (
        <p className="muted small">Choose the two versions you want to compare.</p>
      )}
      {!err && !data && range && range.from && range.to && range.from !== range.to && (
        <div className="card skeleton" style={{ height: 160 }} />
      )}
      {!err && versions && !versions.versions.length && (
        <EmptyState icon="book" title="Nothing to compare yet" text="Versions appear as soon as the Engineer publishes the first build." />
      )}
      {!err && data && (
        <>
          <div className="row wrap between">
            <p className="diff-summary">
              <span className="pill add">+{data.added}</span>
              <span className="pill del">-{data.removed}</span>
              <span className="muted small">
                v{range.from} ({data.from.note}) to v{range.to} ({data.to.note}).
                {data.truncated ? " Rows beyond the first " + data.rows.length + " are not shown." : ""}
              </span>
            </p>
            <DiffModeToggle mode={mode} setMode={setMode} />
          </div>
          {!data.changed
            ? <EmptyState icon="check" title="No differences" text="These two builds render the same page." />
            : <DiffBody rows={data.rows} side={data.side} mode={mode} />}
        </>
      )}
    </Modal>
  );
}
