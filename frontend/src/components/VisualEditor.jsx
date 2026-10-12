/* The visual editor's side panel: one selected element, its place in the source, and one reviewed patch.
   Nothing here re-implements the workspace — the patch travels the same checkpoint-before, validate-after
   path a typed change takes, so "applied as v8, restores from w8" means the same thing in either tab: w8 is
   the snapshot taken before the edit, which is why restoring it puts the page back rather than forward. */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DiffBody, DiffModeToggle } from "./DiffView";
import AiWorking from "./AiWorking";
import EmptyState from "./EmptyState";
import Icon from "./Icon";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const SUGGESTIONS = [
  "Make this navbar smaller and more professional.",
  "Change this card to a glassmorphism design.",
  "Improve the spacing and typography here.",
  "Add a smooth hover animation to this button.",
  "Make this section responsive on mobile.",
];

const REFUSAL = {
  "no-page": "no HTML page in this workspace can be read",
  "no-tag": "the frame reported no tag name",
  "not-found": "not in the published source",
  stale: "the page moved after this frame was rendered",
  ambiguous: "several elements match and no position was reported",
};

const selLabel = (el) => `<${el?.tag || "?"}>`
  + (el?.id ? ` #${el.id}` : "")
  + (el?.classes?.length ? ` .${el.classes.join(".")}` : "");

/* The frame sends attribute pairs in document order; a proposal read back from run state holds a mapping.
   Both describe the same node, so the summary normalises rather than assuming which one arrived. */
const attrsOf = (el) => {
  const a = el?.attrs;
  if (!a) return [];
  return (Array.isArray(a) ? a : Object.entries(a))
    .filter((p) => Array.isArray(p) && p[0])
    .map(([k, v]) => [String(k), String(v ?? "")]);
};

const tone = (s) => (s === "error" ? "err" : s === "warning" ? "warn" : "");

/** Ask for a change to the element the preview frame reported, review the patch, then apply or reject it. */
export default function VisualEditor({ runId, version, element, picking, onPick, onClear,
                                      setRun, refresh, reload, working, editable, undo, onThemeRequest }) {
  const toast = useToast();
  const [map, setMap] = useState(null);
  const [mapBusy, setMapBusy] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [plan, setPlan] = useState(null);
  const [note, setNote] = useState("");
  const [list, setList] = useState([]);
  const [mode, setMode] = useState("unified");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");

  const loadList = useCallback(() => {
    if (!runId) { setList([]); return; }
    api.visualProposals(runId).then((d) => setList(d.proposals || [])).catch(() => setList([]));
  }, [runId]);

  useEffect(() => { loadList(); }, [loadList, version]);

  // A new selection is a new question: the old mapping and the old patch no longer describe this element.
  useEffect(() => {
    setPlan(null); setErr("");
    if (!runId || !element) { setMap(null); setMapBusy(false); return undefined; }
    let live = true;
    setMapBusy(true); setMap(null);
    api.visualLocate(runId, element)
      .then((m) => live && setMap(m))
      .catch((e) => live && setErr(e.message))
      .finally(() => { if (live) setMapBusy(false); });
    return () => { live = false; };
  }, [runId, element]);

  const propose = async (e) => {
    e.preventDefault();
    const text = instruction.trim();
    if (text.length < 3 || !map?.found) return;
    setBusy("plan"); setPlan(null); setErr("");
    try { setPlan(await api.visualPlan(runId, { element, instruction: text, base_version: map.version })); }
    catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      setRun(await api.visualApply(runId, { id: plan.proposal.id, base_version: plan.base_version }));
      toast("Change queued — the page is rebuilding and re-checking", "success");
      setPlan(null); setInstruction(""); setNote("");
      await refresh();
      await reload();
      loadList();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const reject = async () => {
    setBusy("reject");
    try {
      await api.visualReject(runId, { id: plan.proposal.id, reason: note.trim() });
      toast("Rejected — nothing was written to the workspace", "info");
      setPlan(null); setNote("");
      loadList();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const step = async (w) => {
    setBusy(w ? `w${w}` : "undo");
    try {
      // one reviewed step back: the workspace snapshots the state being left, so this is itself undoable
      setRun(await (w ? api.wsRestore(runId, w, version) : api.wsUndo(runId, version)));
      toast(w ? `Restoring w${w}` : "Undoing the last recorded change", "info");
      setPlan(null);
      await refresh();
      await reload();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const canPropose = !!map?.found && instruction.trim().length >= 3 && !mapBusy && !busy && !working;

  return (
    <aside className="card stack ve-panel" aria-label="Visual AI editor">
      <div className="row between wrap">
        <h2>Visual AI editor</h2>
        <span className={`pill ${element ? "ok" : ""}`}>{element ? "element selected" : "nothing selected"}</span>
      </div>

      {!element && (
        <>
          <EmptyState icon="target" title={picking ? "Click any element in the preview" : "Select something to change"}
            text="Arm the preview, then click a navbar, button, card, image, form, heading or section. The panel maps it back to the file and line that declare it before the model is asked for anything." />
          {!!undo?.can_undo && (
            <button className="btn ghost small" onClick={() => step()} disabled={!editable || !!busy}>
              <Icon name="undo" size={14} /> Undo the last recorded change (w{undo.next_undo})
            </button>
          )}
        </>
      )}

      {element && (
        <>
          <div className="ve-sel">
            <div className="row wrap">
              <strong className="mono">{selLabel(element)}</strong>
              <span className="pill">{element.matches} match(es)</span>
              {element.index != null && <span className="pill">#{element.index + 1} of them</span>}
            </div>
            {!!element.text && <p className="muted small">{element.text}</p>}
            {!!attrsOf(element).length && (
              <div className="row wrap ve-attrs">
                {attrsOf(element).map(([k, v]) => (
                  <span key={k} className="pill mono" title={`${k}="${v}"`}>{v ? `${k}="${v}"` : k}</span>
                ))}
              </div>
            )}
            {!!element.path && <p className="muted small mono">{element.path}</p>}
            <div className="row wrap">
              <button className="btn ghost small" onClick={onPick} disabled={working}>
                <Icon name="target" size={14} /> Pick another
              </button>
              <button className="btn ghost small" onClick={onClear}><Icon name="close" size={14} /> Clear</button>
            </div>
          </div>

          {mapBusy && <AiWorking label="Mapping this element to its source" detail={false} />}
          {err && !map && <div className="error" role="alert">{err}</div>}

          {map && !map.found && (
            <div className="ve-refusal" role="status">
              <div className="row wrap"><Icon name="alert" size={15} /><strong>Not mappable</strong>
                <span className="pill warn mono">{map.reason}</span></div>
              <p className="muted small">{map.message}</p>
              <ul className="ve-refs">
                {(map.candidates || []).map((c, i) => (
                  <li key={`${c.file}-${c.line}-${i}`}>
                    <div className="row wrap"><span className="mono">{c.file}</span>
                      <span className="pill">line {c.line}</span></div>
                    <p className="muted small mono">{`<${c.tag}${c.id ? ` id="${c.id}"` : ""}${c.classes?.length ? ` class="${c.classes.join(" ")}"` : ""}>`}</p>
                  </li>
                ))}
              </ul>
              <p className="muted small">{REFUSAL[map.reason] || "the mapping refused"} — no file path is
                invented to keep the request moving. {map.reason === "ambiguous"
                  ? "Pick an element that carries its own id or class." : "Refresh the preview and select again."}</p>
            </div>
          )}

          {map?.found && (
            <div className="ve-map">
              <div className="row wrap">
                <span className="pill mono">{map.source.file}</span>
                <span className="pill">line {map.source.line}</span>
                <span className={`pill ${map.confidence === "exact" ? "ok" : "warn"}`}>{map.via} · {map.confidence}</span>
              </div>
              <pre className="ve-snip mono">{map.source.snippet}</pre>
              {(map.styling?.length || map.scripting?.length) ? (
                <>
                  {!!map.styling?.length && (
                    <section>
                      <h4>Styled by</h4>
                      <ul className="ve-refs">
                        {map.styling.map((r) => (
                          <li key={`${r.basis}-${r.line}-${r.kind}`}>
                            <div className="row wrap"><span className="mono">{r.basis}:{r.line}</span>
                              <span className="pill">{r.kind}</span></div>
                            <p className="muted small mono">{r.snippet}</p>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  {!!map.scripting?.length && (
                    <section>
                      <h4>Reached by script</h4>
                      <ul className="ve-refs">
                        {map.scripting.map((r) => (
                          <li key={`${r.basis}-${r.line}-${r.kind}`}>
                            <div className="row wrap"><span className="mono">{r.basis}:{r.line}</span>
                              <span className="pill">{r.kind}</span></div>
                            <p className="muted small mono">{r.snippet}</p>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                </>
              ) : <p className="muted small">No rule or script in this build names this element by id or class,
                so only the file above is in scope.</p>}
            </div>
          )}

          <form className="stack" onSubmit={propose}>
            <label>Say what to change about it
              <textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)}
                maxLength={500} placeholder="Make this navbar smaller and more professional."
                aria-label="Change requested for the selected element" />
            </label>
            {!instruction && (
              <div className="row wrap ve-hints">
                {SUGGESTIONS.slice(0, 3).map((s) => (
                  <button key={s} type="button" className="pill" onClick={() => setInstruction(s)}>{s}</button>
                ))}
              </div>
            )}
            <p className="muted small">One model call, one bounded patch, and nothing written until you apply
              it. {map?.found ? `The patch may only name ${map.source.file} or the rules that reference this element.` : "Proposing needs a mapping first."}</p>
            <button className="btn primary" disabled={!canPropose}>
              <Icon name="sparkle" size={15} /> {busy === "plan" ? "Asking the editor…" : "Propose the change"}
            </button>
            {working && <p className="muted small">The crew is rebuilding this page — select again once it settles.</p>}
          </form>

          {onThemeRequest && (
            <section className="ve-wholesite stack">
              <p className="muted small">This panel edits the one selected element. A sentence about the look of the
                whole site belongs in the Theme studio, which changes the page's design tokens once instead of patching
                every element — it will say which words it understood and refuse the ones it cannot honour.</p>
              <div className="row wrap">
                <button type="button" className="btn ghost small" disabled={!instruction.trim()}
                  onClick={() => onThemeRequest(instruction.trim())}>
                  <Icon name="palette" size={14} /> Send this to the Theme studio
                </button>
                <button type="button" className="btn ghost small" disabled={!onThemeRequest}
                  onClick={() => onThemeRequest("")}>
                  <Icon name="sliders" size={14} /> Open Theme studio
                </button>
              </div>
            </section>
          )}

          {plan && (
            <section className="ve-plan stack">
              <div className="row wrap between">
                <h3>{plan.headline}</h3>
                <span className={`pill ${plan.safe_to_apply ? "ok" : "err"}`}>
                  {plan.safe_to_apply ? "no blocking risks" : `${plan.impact.counts.errors} blocking risk(s)`}
                </span>
              </div>
              <div className="row wrap">
                <span className="pill mono">{plan.proposal.id}</span>
                <span className="pill">{plan.patch.op} · {plan.patch.file}</span>
                <span className="pill">{plan.region || "end of file"}</span>
                <span className={`pill ${plan.targeted ? "ok" : "warn"}`}>{plan.targeted ? "names the selected element" : "not about this element"}</span>
                <span className="pill">{plan.limits.revisions_left} revision(s) left</span>
              </div>
              {!plan.targeted && <p className="muted small">{plan.warning}</p>}
              <dl className="ve-patch">
                <dt>Find</dt><dd className="mono">{plan.patch.find || "(nothing — this appends)"}</dd>
                <dt>Replace with</dt><dd className="mono">{plan.patch.op === "append" ? plan.patch.text : plan.patch.replace}</dd>
                {!!plan.patch.note && (<><dt>Note</dt><dd>{plan.patch.note}</dd></>)}
              </dl>
              <div className="row wrap">
                {plan.affected_files.map((f) => <span key={f} className="pill mono">{f}</span>)}
                <DiffModeToggle mode={mode} setMode={setMode} />
              </div>
              {Object.entries(plan.diffs || {}).map(([name, d]) => (
                <div key={name} className="stack">
                  <p className="muted small mono">{name} · +{d.added} -{d.removed}{d.truncated ? " · rows truncated" : ""}</p>
                  <DiffBody rows={d.rows} side={d.side} mode={mode} />
                </div>
              ))}
              <ul className="risk-list">
                {(plan.impact.risks || []).map((r) => (
                  <li key={`${r.id}-${r.message}`} className={`risk-item ${tone(r.severity)}`}>
                    <div className="row wrap"><strong>{r.id}</strong>
                      <span className={`pill ${tone(r.severity)}`}>{r.severity}</span></div>
                    <p className="small">{r.message}</p>
                  </li>
                ))}
                {!plan.impact.risks?.length && <li className="risk-item"><p className="small">No risks found in this report.</p></li>}
              </ul>
              <label>Why (optional, kept with the record)
                <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200}
                  placeholder="Too much padding and the logo is competing with the links" aria-label="Reason for this decision" />
              </label>
              <div className="row wrap">
                <button className="btn primary" onClick={apply} disabled={!editable || !!busy || !plan.safe_to_apply}>
                  <Icon name="check" size={15} /> {busy === "apply" ? "Applying…" : "Apply and re-check"}
                </button>
                <button className="btn ghost" onClick={reject} disabled={!!busy}>
                  <Icon name="close" size={15} /> {busy === "reject" ? "…" : "Reject"}
                </button>
              </div>
              <p className="muted small">Measured against page v{plan.base_version}
                {!editable && " — applying needs the run back at the approval gate"}
                {working ? " — it is working now." : "."}</p>
            </section>
          )}

          {!!undo?.can_undo && (
            <button className="btn ghost small" onClick={() => step()} disabled={!editable || !!busy}>
              <Icon name="undo" size={14} /> Undo the last recorded change (w{undo.next_undo})
            </button>
          )}
        </>
      )}

      <section className="stack ve-history">
        <div className="row between wrap">
          <h3>Visual edits on this run</h3>
          <Link className="muted small" to="/versions">Version history</Link>
        </div>
        {!list.length && <p className="muted small">None yet. A proposal is recorded whether you apply it,
          reject it, or leave it unread.</p>}
        <ul className="plan-list">
          {list.map((p) => (
            <li key={p.id} className={`plan-item ${p.status === "applied" ? "applied" : p.status === "rejected" ? "rejected" : "pending"}`}>
              <div className="row wrap between">
                <div className="row wrap">
                  <span className={`pill ${p.status === "applied" ? "ok" : p.status === "rejected" ? "err" : ""}`}>{p.status}</span>
                  <strong className="mono">{p.id}</strong>
                  <span className="pill">{p.element?.tag}</span>
                </div>
                <span className="muted small">{timeAgo(p.at)} · v{p.version}</span>
              </div>
              <p className="muted small">{p.instruction}</p>
              <p className="muted small mono">{p.source?.file}:{p.source?.line} · {p.patch?.op} · +{p.lines_added}
                -{p.lines_removed}{p.result?.version ? ` · applied as v${p.result.version}` : ""}
                {p.result?.workspace_version ? ` · restores from w${p.result.workspace_version}` : ""}
                {p.result?.reason ? ` · “${p.result.reason}”` : ""}
                {p.result?.error ? ` · ${p.result.error}` : ""}</p>
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
    </aside>
  );
}
