/* The assistant in the IDE's right column: plain English in, a measured diff out, nothing written until
   the reviewer says so.
   There is no second AI here. `/ide/plan` asks the same crew agent the review gate asks, against the same
   stored files the tabs show, and `/ide/apply` hands the change to the same patch pipeline a typed change
   takes - checkpoint first, sanitizer and Chromium checks after, one revision spent. So "applied as v9,
   restores from w9" means exactly what it means on the workspace page.
   The model sees only file contents it was given and can only name those files back; keys stay server-side. */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { DiffModeToggle, FileDiffList } from "../DiffView";
import AiWorking from "../AiWorking";
import Icon from "../Icon";
import { useToast } from "../../toast";
import { timeAgo } from "../../utils";

const tone = (s) => (s === "error" ? "err" : s === "warning" ? "warn" : "");

const SUGGESTIONS = [
  "Tighten the spacing in the sign-up section.",
  "Make the primary button's hover state clearer.",
  "Shorten the hero headline without changing its meaning.",
];

/** Which files the model is shown: the ones ticked, or the ones the request names. */
const scopeHint = (scope) => (scope.length
  ? `Only these will be sent: ${scope.join(", ")}.`
  : "Nothing ticked: files the request names are sent first, then the page itself, until the size budget is full.");

export default function AssistantPanel({ runId, version, files = [], editable, working, undo,
                                         setRun, refresh, onClose }) {
  const toast = useToast();
  const [instruction, setInstruction] = useState("");
  const [scope, setScope] = useState([]);
  const [plan, setPlan] = useState(null);
  const [ack, setAck] = useState(false);
  const [note, setNote] = useState("");
  const [list, setList] = useState([]);
  const [mode, setMode] = useState("unified");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const loadList = useCallback(() => {
    if (!runId) { setList([]); return; }
    api.ideAssistantProposals(runId).then((d) => setList(d.proposals || [])).catch(() => setList([]));
  }, [runId]);

  useEffect(() => { loadList(); }, [loadList, version]);

  // The page moved underneath a proposal the reviewer may still be reading: drop it rather than let them
  // apply a diff that no longer describes the stored bytes. /ide/apply would refuse it anyway.
  useEffect(() => { setPlan(null); }, [version]);

  const maxFiles = plan?.limits?.max_files_sent || 8;
  const names = files.map((f) => f.name);

  const toggleScope = (name) => setScope((s) => (s.includes(name) ? s.filter((n) => n !== name)
    : s.length >= maxFiles ? s : [...s, name]));

  const ask = async (e) => {
    e?.preventDefault();
    const text = instruction.trim();
    if (text.length < 3) return;
    setBusy("plan"); setPlan(null); setErr(""); setAck(false);
    try {
      setPlan(await api.ideAssistantPlan(runId, { instruction: text, files: scope, base_version: version }));
      // A proposal exists on the run now, whether or not this panel stays open to read it.
      loadList();
    } catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      setRun(await api.ideAssistantApply(runId, { id: plan.proposal.id, base_version: plan.base_version }));
      toast("Change queued — checkpoint first, then the page rebuilds and re-checks", "success");
      setPlan(null); setInstruction(""); setNote(""); setAck(false);
      await refresh();
      loadList();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const reject = async () => {
    setBusy("reject");
    try {
      await api.ideAssistantReject(runId, { id: plan.proposal.id, reason: note.trim() });
      toast("Rejected — nothing was written to the workspace", "info");
      setPlan(null); setNote("");
      loadList();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const step = async (w) => {
    setBusy(w ? `w${w}` : "undo");
    try {
      setRun(await (w ? api.wsRestore(runId, w, version) : api.wsUndo(runId, version)));
      toast(w ? `Restoring w${w}` : "Undoing the last recorded change", "info");
      setPlan(null);
      await refresh();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const diffs = Object.entries(plan?.diffs || {}).map(([file, d]) => ({ file, ...d }));
  const canAsk = instruction.trim().length >= 3 && !busy && !working && !!names.length;

  return (
    <div className="ide-ai ide-panel" aria-label="AI coding assistant">
      <div className="ide-panel-head">
        <strong>AI assistant</strong>
        <span className="row wrap ide-ai-head-pills">
          <span className={`pill ${working ? "warn" : editable ? "ok" : ""}`}>
            {working ? "crew is working" : editable ? "at the gate" : "not at the gate"}</span>
          <button className="ide-mini" onClick={onClose} title="Close the assistant panel"
            aria-label="Close the assistant panel"><Icon name="close" size={14} /></button>
        </span>
      </div>

      <form className="stack" onSubmit={ask}>
        <label className="stack">Ask for a change
          <textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)}
            maxLength={plan?.limits?.max_instruction_chars || 500}
            placeholder="Tighten the spacing in the sign-up section."
            aria-label="Change to ask the assistant for" />
        </label>
        {!instruction && !!names.length && (
          <div className="row wrap ide-ai-hints">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" className="pill" onClick={() => setInstruction(s)}>{s}</button>
            ))}
          </div>
        )}
        {!!names.length && (
          <details className="ide-ai-scope">
            <summary>Which files to send ({scope.length ? scope.join(", ") : "chosen from the request"})</summary>
            <div className="row wrap">
              {names.map((n) => (
                <label key={n} className="ide-check">
                  <input type="checkbox" checked={scope.includes(n)} disabled={!scope.includes(n) && scope.length >= maxFiles}
                    onChange={() => toggleScope(n)} />
                  <span className="mono">{n}</span>
                </label>
              ))}
            </div>
            <p className="muted small">{scopeHint(scope)} Large files are clipped and the panel says which.</p>
          </details>
        )}
        <button className="btn primary small" type="submit" disabled={!canAsk}>
          <Icon name="sparkle" size={14} /> {busy === "plan" ? "Asking…" : "Propose the change"}
        </button>
        {!names.length && <p className="muted small">This run has published no files yet, so there is nothing
          for the assistant to read. Build the page first.</p>}
        {working && <p className="muted small">The crew is working on this run right now — ask once it settles
          at the approval gate.</p>}
      </form>

      {busy === "plan" && <AiWorking label="Reading the stored files and drafting the edit" detail={false} />}
      {err && <div className="error" role="alert">{err}</div>}

      {plan && (
        <section className="stack ide-ai-plan">
          <div className="row between wrap">
            <strong>{plan.proposal.summary || plan.headline}</strong>
            <span className={`pill ${plan.safe_to_apply ? "ok" : "err"}`}>
              {plan.safe_to_apply ? "no blocking risks" : `${plan.impact.counts.errors} blocking risk(s)`}
            </span>
          </div>
          <div className="row wrap ide-ai-pills">
            <span className="pill mono">{plan.proposal.id}</span>
            <span className="pill">v{plan.base_version}</span>
            <span className="pill">{plan.proposal.changes.length} change(s)</span>
            <span className="pill">+{plan.projection.lines_added} -{plan.projection.lines_removed}</span>
            <span className="pill">{plan.limits.revisions_left} revision(s) left</span>
          </div>
          <p className="muted small">{plan.headline} Measured against the bytes stored at page v{plan.base_version}.</p>

          <ul className="ide-ai-affected">
            {plan.affected.map((a, i) => (
              <li key={`${a.file}-${i}`}>
                <div className="row wrap">
                  <strong className="mono">{a.file}</strong>
                  <span className="pill">{a.op}</span>
                  <span className={`pill ${a.save_via ? "" : "warn"}`}>{a.kind}</span>
                  <span className="muted small">+{a.lines_added} -{a.lines_removed}</span>
                </div>
                {!!a.note && <p className="muted small">{a.note}</p>}
                {!!a.why && <p className="muted small">{a.why}</p>}
              </li>
            ))}
          </ul>

          <div className="row wrap ide-ai-diffhead">
            <span className="muted small">Diff — {diffs.length} file(s)</span>
            <DiffModeToggle mode={mode} setMode={setMode} />
          </div>
          <FileDiffList files={diffs} mode={mode} />

          {(plan.sent_files?.length || plan.clipped_files?.length) ? (
            <p className="muted small">Sent to the model: {plan.sent_files.join(", ")}
              {plan.clipped_files.length ? ` · clipped to fit the budget: ${plan.clipped_files.join(", ")}` : ""}.</p>
          ) : null}

          <ul className="risk-list">
            {(plan.impact.risks || []).map((r) => (
              <li key={`${r.id}-${r.message}`} className={`risk-item ${tone(r.severity)}`}>
                <div className="row wrap"><strong>{r.id}</strong>
                  <span className={`pill ${tone(r.severity)}`}>{r.severity}</span></div>
                <p className="small">{r.message}</p>
                {!!r.files?.length && <p className="muted small mono">{r.files.join(", ")}</p>}
              </li>
            ))}
            {!plan.impact.risks?.length && <li className="risk-item"><p className="small">Nothing in this
              workspace breaks under the change as measured.</p></li>}
          </ul>

          {!plan.safe_to_apply && (
            <label className="ide-check ide-ai-ack">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>I have read the {plan.impact.counts.errors} blocking risk(s) above. They are measured
                against the whole request, and a change set can answer one of them - this stays the reviewer's
                call, not a block.</span>
            </label>
          )}

          <label className="stack">Why (optional, kept with the record)
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200}
              placeholder="The button reads as disabled" aria-label="Reason for this decision" />
          </label>

          <div className="row wrap">
            <button className="btn primary small" onClick={apply}
              disabled={!editable || !!busy || (!plan.safe_to_apply && !ack)}>
              <Icon name="check" size={14} /> {busy === "apply" ? "Queuing…" : "Accept and apply"}
            </button>
            <button className="btn ghost small" onClick={reject} disabled={!!busy}>
              <Icon name="close" size={14} /> {busy === "reject" ? "…" : "Reject"}
            </button>
            <button className="btn ghost small" onClick={() => { setPlan(null); setErr(""); }} disabled={!!busy}>
              <Icon name="refresh" size={14} /> Revise the request
            </button>
          </div>
          <p className="muted small">Accepting hands the change to {plan.applies_through}, so it spends one of
            this run's revisions{editable ? "" : " and needs the run back at the approval gate"}
            {working ? " — it is working now." : "."} A snapshot of the state being left is taken first, which
            is what the undo below restores.</p>
        </section>
      )}

      {!!undo?.can_undo && (
        <button className="btn ghost small" onClick={() => step()} disabled={!editable || !!busy}>
          <Icon name="undo" size={14} /> Undo the last recorded change (w{undo.next_undo})
        </button>
      )}

      <section className="stack ide-ai-history">
        <div className="row between wrap">
          <strong>Assistant edits on this run</strong>
          <span className="row ide-ai-history-head">
            <button className="ide-mini" onClick={loadList} title="Reload this list"
              aria-label="Reload the assistant list"><Icon name="refresh" size={14} /></button>
            <Link className="muted small" to="/versions">Version history</Link>
          </span>
        </div>
        {!list.length && <p className="muted small">None yet. A proposal is recorded whether you accept it,
          reject it, or leave it unread — and it writes nothing until you accept.</p>}
        <ul className="plan-list">
          {list.map((p) => (
            <li key={p.id} className={`plan-item ${p.status === "applied" ? "applied"
              : p.status === "rejected" ? "rejected" : "pending"}`}>
              <div className="row wrap between">
                <div className="row wrap">
                  <span className={`pill ${p.status === "applied" ? "ok" : p.status === "rejected" ? "err" : ""}`}>
                    {p.status}</span>
                  <strong className="mono">{p.id}</strong>
                  <span className="pill">v{p.version}</span>
                  <span className="pill">{(p.files || []).length} file(s)</span>
                </div>
                <span className="muted small">{timeAgo(p.at)}</span>
              </div>
              <p className="muted small">{p.instruction}</p>
              <p className="muted small mono">{(p.files || []).join(", ")} · +{p.lines_added} -{p.lines_removed}
                {p.result?.version ? ` · applied as v${p.result.version}` : ""}
                {p.result?.workspace_version ? ` · restores from w${p.result.workspace_version}` : ""}
                {p.result?.check_errors != null ? ` · ${p.result.check_errors} check error(s)` : ""}
                {p.result?.reason ? ` · “${p.result.reason}”` : ""}
                {p.result?.error ? ` · ${p.result.error}` : ""}
                {p.clipped_files?.length ? ` · clipped: ${p.clipped_files.join(", ")}` : ""}</p>
              {p.status === "applied" && !!p.result?.workspace_version && (
                <button className="btn ghost small" onClick={() => step(p.result.workspace_version)}
                  disabled={!editable || !!busy}>
                  <Icon name="redo" size={14} /> Restore the page from before this edit
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
