/* Real features on a live run: plain English in, one reviewable build out.

   The panel never calls a feature "done" on its own authority. `/plan` answers what a sentence means and
   records nothing; `/propose` measures the patch against this page and diffs it; only `/apply` hands it to
   the crew's pipeline, which snapshots the whole file set first and re-runs the sanitizer, the Chromium
   checks and the readiness score afterwards. Every status below comes from the capability catalog the
   server publishes, so a checkout whose payment provider is unconfigured stays "needs your account or keys"
   and is never reported as a working store.

   A build writes the server half beside the page too — `server.py`, `db.py`, `schema.sql`,
   `env_template.txt`, `feature_client.js`, `requirements.txt`, `FEATURES.md` and `SETUP.md`. None of that
   runs until the owner installs and starts it, which is why each feature's own setup steps are printed here
   instead of being summarised away.
*/
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DiffBody, DiffModeToggle } from "./DiffView";
import EmptyState from "./EmptyState";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const MAX_ASK = 500;

// The catalog's own three states, in the reader's language. Nothing here upgrades one of them.
const TONE = { generated: "ok", scaffold: "", "needs-external-setup": "warn" };
const SHORT = { generated: "works in the page now", scaffold: "runnable source - you start it",
  "needs-external-setup": "needs your account or keys" };
const NEED_LABEL = { page: "frontend changes", server: "backend logic", database: "database changes",
  integration: "external integrations" };
const kb = (bytes) => `${Math.max(1, Math.round((bytes || 0) / 1024))} KB`;

/** One capability as the build sees it: what it takes, what it writes, what is still yours to do. */
function FeatureRow({ f }) {
  const waiting = f.status && f.status !== "generated";
  return (
    <li className="fp-item">
      <div className="row wrap between">
        <strong>{f.label}</strong>
        <span className={`pill ${TONE[f.status] || ""}`}>{SHORT[f.status] || f.status}</span>
      </div>
      <div className="row wrap">
        {(f.needs || []).map((n) => <span key={n} className="pill">{NEED_LABEL[n] || n}</span>)}
        {!!f.routes?.length && <span className="pill mono">{f.routes.length} endpoint(s)</span>}
        {!!f.tables?.length && <span className="pill mono">{f.tables.length} table(s)</span>}
        {!f.env?.length && !waiting && <span className="pill ok">nothing to configure</span>}
      </div>
      {!!f.routes?.length && <p className="muted small mono">{f.routes.join("  ")}</p>}
      {!!f.tables?.length && <p className="muted small mono">{f.tables.join(", ")}</p>}
      {!!f.env?.length && (
        <p className="muted small">Reads these variables: {f.env.join(", ")} — names only, never a value.</p>
      )}
      {!!f.setup?.length && (
        <ul className="plan-steps">{f.setup.map((s, i) => <li key={`${f.key}-s${i}`}>{i + 1}. {s}</li>)}</ul>
      )}
      <p className="muted small">{f.limits}</p>
    </li>
  );
}

/** The files a build ships, with the role each one plays. Sizes are measured, not estimated. */
function FileRows({ files, pageName }) {
  return (
    <ul className="ve-refs">
      {(files || []).map((f) => (
        <li key={f.name}>
          <div className="row wrap">
            <span className="mono">{f.name}</span>
            <span className={`pill ${f.name === pageName ? "ok" : ""}`}>{kb(f.bytes)}</span>
            {f.role === "page" && <span className="pill">into the page block</span>}
          </div>
          {f.note && <p className="muted small">{f.note}</p>}
        </li>
      ))}
    </ul>
  );
}

/** Ask for a website feature in plain English, read the measured build, then apply or leave it. */
export default function FeaturesPanel({ runId, version, setRun, refresh, reload, working, editable, undo,
                                        requestedKeys }) {
  const toast = useToast();
  const [catalog, setCatalog] = useState(null);
  const [catErr, setCatErr] = useState("");
  const [status, setStatus] = useState(null);
  const [statusErr, setStatusErr] = useState("");
  const [ask, setAsk] = useState("");
  const [keys, setKeys] = useState([]);
  const [fromBrief, setFromBrief] = useState(false);
  const [report, setReport] = useState(null);     // what the ask means; records nothing
  const [refusal, setRefusal] = useState("");     // the planner's own reason for saying no
  const [proposal, setProposal] = useState(null); // the patch, its diff and its projection
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [mode, setMode] = useState("unified");
  const [note, setNote] = useState("");

  useEffect(() => { api.capabilities().then(setCatalog).catch((e) => setCatErr(e.message)); }, []);

  const loadStatus = useCallback(() => {
    if (!runId) { setStatus(null); return; }
    api.featureStatus(runId).then((d) => { setStatus(d); setStatusErr(""); })
      .catch((e) => { setStatus(null); setStatusErr(e.message); });
  }, [runId]);

  useEffect(() => { loadStatus(); }, [loadStatus, version]);

  // A patch measured against the old page says nothing about the new one.
  useEffect(() => { setProposal(null); setErr(""); }, [runId, version]);
  // Editing the ask invalidates the measurement of it, the same way moving a slider invalidates a preview.
  useEffect(() => { setReport(null); setRefusal(""); }, [runId, version, ask, keys.join(",")]);

  const labelOf = useCallback((key) => catalog?.capabilities?.find((c) => c.key === key)?.label || key,
    [catalog]);

  // The brief's own tick list arrives as a request, not a build: it pre-fills the picker and nothing more.
  const seeded = useRef("");
  useEffect(() => {
    const list = (requestedKeys || []).join(",");
    const mark = `${runId}:${list}`;
    if (!list || seeded.current === mark) return;
    seeded.current = mark;
    setKeys(requestedKeys.filter((k) => catalog?.capabilities?.some((c) => c.key === k)));
    setFromBrief(true);
  }, [runId, requestedKeys, catalog]);

  const cap = status?.limits?.max_features_per_build || 16;
  const blocked = !!status?.busy || working;
  const outOfRevisions = (status?.limits?.revisions_left ?? 1) === 0;
  const canAsk = !!catalog && !!status && !!runId && (ask.trim().length > 2 || keys.length > 0) && !busy;

  const toggle = (key) => setKeys((list) => (list.includes(key)
    ? list.filter((k) => k !== key)
    : (list.length >= cap ? list : [...list, key])));

  const planIt = async () => {
    setBusy("plan"); setReport(null); setRefusal(""); setProposal(null); setErr("");
    try { setReport(await api.featurePlan(runId, { request: ask.trim(), keys, base_version: version })); }
    catch (ex) { setRefusal(ex.message); } finally { setBusy(""); }
  };

  const propose = async () => {
    setBusy("propose"); setProposal(null); setErr("");
    try {
      setProposal(await api.featurePropose(runId, { request: ask.trim(), keys, base_version: version }));
      loadStatus();
    } catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      // the version this patch was measured against, so a change that landed in another tab is refused
      setRun(await api.featureApply(runId, { id: proposal.proposal.id, base_version: proposal.base_version }));
      toast("Feature build queued — the page is rebuilding and re-checking", "success");
      setProposal(null); setReport(null); setNote("");
      await refresh();
      await reload();
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const reject = async () => {
    setBusy("reject");
    try {
      await api.featureReject(runId, { id: proposal.proposal.id, reason: note.trim() });
      toast("Rejected — no file in this workspace was written", "info");
      setProposal(null); setNote("");
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  // The snapshot taken before that build: restoring it puts the page and every source file back.
  const step = async (w) => {
    setBusy(`w${w}`);
    try {
      // a named snapshot rewinds to it; no argument means the workspace's own undo step
      setRun(await (w ? api.wsRestore(runId, w, version) : api.wsUndo(runId, version)));
      toast(w ? `Restoring the file set from before w${w}` : "Undoing the last recorded change", "info");
      setProposal(null); setReport(null);
      await refresh();
      await reload();
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const present = status?.panels_present || [];
  const missing = status?.panels_missing || [];
  const open = (status?.proposals || []).find((p) => p.status === "proposed");
  const applied = (status?.proposals || []).find((p) => p.status === "applied");
  const waitingRows = useMemo(() => (applied?.features || []).filter((f) => f.status !== "generated"),
    [applied]);
  const picked = useMemo(() => (catalog?.capabilities || []).filter((c) => keys.includes(c.key)),
    [catalog, keys]);
  const pickedWaiting = picked.filter((c) => c.status !== "generated");

  return (
    <aside className="card stack ve-panel" aria-label="Feature studio">
      <div className="row between wrap">
        <h2>Feature studio</h2>
        <span className={`pill ${proposal ? "warn" : report ? "ok" : ""}`}>
          {proposal ? "build to review" : report ? "measured, nothing recorded" : "describe what you need"}
        </span>
      </div>

      <div className="row wrap">
        <span className="pill">page v{version}</span>
        <span className={`pill ${editable ? "ok" : ""}`}>{editable ? "at the approval gate" : "not editable now"}</span>
        {status && <span className="pill">{status.count}/{status.max} proposal(s)</span>}
        {open && <span className="pill warn">{open.id} awaiting a decision</span>}
        {status && <span className="pill">{status.limits.revisions_left} revision(s) left</span>}
        <span className={`pill ${present.length ? "ok" : ""}`}>{present.length} panel(s) on this page</span>
        {status?.server_files && <span className="pill">server source in the workspace</span>}
      </div>

      {catErr && <ErrorState title="The feature catalog could not be read" message={catErr}
        retry={() => { setCatErr(""); api.capabilities().then(setCatalog).catch((e) => setCatErr(e.message)); }} />}
      {statusErr && <ErrorState title="This run’s feature history could not be read" message={statusErr}
        retry={loadStatus} />}
      {(catErr || statusErr) && <p className="muted small">Nothing has been written to this workspace by that
        failure: the catalog and the history are both read-only calls.</p>}

      {status?.panels_declared && (
        <div className="ve-refusal" role="status">
          <div className="row wrap"><Icon name="alert" size={15} /><strong>A build is recorded, but its panels are gone</strong></div>
          <p className="muted small">{applied?.id} was applied and this page now carries no feature block. A crew
            revision redraws the page from the brief, which drops panels the same way it drops any other markup —
            so the record is kept, and the honest reading is that the feature is not live. Plan the features again
            against this version and apply the new patch.</p>
        </div>
      )}

      {!!missing.length && !status?.panels_declared && (
        <div className="ve-refusal" role="status">
          <div className="row wrap"><Icon name="alert" size={15} />
            <strong>{missing.length} recorded feature(s) are not on this page</strong></div>
          <p className="muted small">{missing.map(labelOf).join(", ")} were applied to an earlier version and are
            not in the block this page carries now. Ask for them again to write them into v{version}; nothing was
            assumed still-present here.</p>
        </div>
      )}

      {!!applied && !!waitingRows.length && (
        <section className="ve-plan stack">
          <div className="row wrap between">
            <h3>Still waiting on you — {applied.id}</h3>
            <span className="pill warn">{waitingRows.length} feature(s) not yet live</span>
          </div>
          <p className="muted small">{applied.summary}</p>
          <ul className="fp-list">{waitingRows.map((f) => <FeatureRow key={f.key} f={f} />)}</ul>
          {!!applied.env?.length && (
            <p className="muted small">Set these in <code className="inline-code">env_template.txt</code> and start
              the server with the command in <code className="inline-code">SETUP.md</code>:
              {" "}{applied.env.join(", ")}</p>
          )}
          <p className="muted small">The page itself is published and works; the panels that call an API report
            that the API is not reachable until you run <code className="inline-code">server.py</code>. That answer
            is the truth, not a bug — a published page is not allowed to make network calls.</p>
        </section>
      )}

      <form className="stack" onSubmit={(e) => { e.preventDefault(); planIt(); }}>
        <label>What should this site do?
          <textarea value={ask} onChange={(e) => setAsk(e.target.value)} maxLength={MAX_ASK} rows={3}
            placeholder="Visitors can book a workshop slot, and I need a staff area to see the bookings"
            aria-label="Feature request in your own words" />
        </label>
        <span className="muted small">{ask.length}/{MAX_ASK} characters. Plain words are enough — the ask is
          matched against the features this product has real source for, and a sentence that names none is
          refused rather than answered with something close.</span>

        <div className="field">
          <span className="side-label">Or pick them directly</span>
          {!catalog && !catErr && <span className="muted small">Reading the feature catalog…</span>}
          <div className="row wrap" role="group" aria-label="Features this product can build">
            {(catalog?.capabilities || []).map((c) => {
              const on = keys.includes(c.key);
              return (
                <button key={c.key} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on}
                  disabled={!on && (keys.length >= cap || blocked || !!busy)}
                  title={`${c.blurb} — ${c.status_label}`} onClick={() => toggle(c.key)}>
                  {on && <Icon name="check" size={12} />} {c.label}
                  {c.status !== "generated" && (
                    <span className="muted small"> · {c.status === "scaffold" ? "you start it" : "needs your keys"}</span>
                  )}
                </button>
              );
            })}
          </div>
          {!!picked.length && (
            <div className="row wrap">
              <span className="pill">{picked.length} selected</span>
              {pickedWaiting.map((c) => <span key={c.key} className={`pill ${TONE[c.status]}`}>{c.label}: {c.status_label}</span>)}
              <button type="button" className="btn ghost small" onClick={() => { setKeys([]); setFromBrief(false); }}>
                <Icon name="close" size={14} /> Clear the picks
              </button>
            </div>
          )}
          {fromBrief && !!keys.length && (
            <p className="muted small" role="status">Pre-filled from this project’s brief. A tick is a request,
              not a build: nothing is written until the plan below is measured, recorded and applied.</p>
          )}
          {keys.length >= cap && (
            <p className="muted small">{cap} features is the most one build can carry; apply this set and ask
              for the rest after it.</p>
          )}
        </div>

        <div className="row wrap">
          <button className="btn primary" type="submit" disabled={!canAsk}>
            <Icon name="sparkle" size={15} /> {busy === "plan" ? "Reading the catalog…" : "Check what this means"}
          </button>
          {blocked && <span className="pill warn">the crew is working on this run</span>}
        </div>
        <p className="muted small">This costs no model call and writes no file: the answer is read out of the
          capability catalog and measured against page v{version}.</p>
        {outOfRevisions && (
          <p className="error" role="alert">This run has used every revision it is allowed, so a feature build
            cannot be applied to it. Approve this version or start a new run first — checking what an ask means
            stays free, and a recorded proposal simply waits.</p>
        )}
      </form>

      {refusal && (
        <div className="ve-refusal" role="status">
          <div className="row wrap"><Icon name="close" size={15} /><strong>Not built</strong></div>
          <p className="muted small">{refusal}</p>
        </div>
      )}

      {report && (
        <section className="ve-plan stack">
          <div className="row wrap between">
            <h3>What this means</h3>
            <span className={`pill ${TONE[report.overall]}`}>{report.overall_label}</span>
          </div>
          <p className="muted small">{report.summary}</p>
          <div className="row wrap">
            {report.need_words.map((w) => <span key={w} className="pill">{w}</span>)}
            <span className="pill">{report.features.length} feature(s)</span>
            {!!report.introduces?.length && <span className="pill ok">{report.introduces.length} new here</span>}
            {!!report.present_before?.length && (
              <span className="pill">{report.present_before.length} already on the page, kept</span>)}
            {!!report.replacing && <span className="pill">replaces the existing block</span>}
            <span className="pill mono">{report.files.length} file(s)</span>
            <span className="pill mono">{(report.page_bytes || 0).toLocaleString()} page bytes</span>
          </div>
          {!!report.added?.length && (
            <p className="muted small">Pulled in because what you asked for depends on it:
              {" "}{report.added.map(labelOf).join(", ")}.</p>
          )}
          {!!report.named?.length && (
            <p className="muted small">Named by your own words: {report.named.map(labelOf).join(", ")}.</p>
          )}
          <ul className="fp-list">{report.features.map((f) => <FeatureRow key={f.key} f={f} />)}</ul>
          <div className="stack">
            <strong className="small">Files this build writes</strong>
            <FileRows files={report.files} pageName="feature_sections.html" />
          </div>
          {!!report.env?.length && (
            <p className="muted small">Variables it reads: {report.env.join(", ")}. The generated template leaves
              every one empty — a value is never guessed and never hardcoded.</p>
          )}
          {!!report.warnings?.length && (
            <ul className="ds-notes">{report.warnings.map((w, i) => (
              <li key={`w${i}`}><Icon name="alert" size={14} /> {w}</li>))}</ul>
          )}
          <div className="row wrap">
            <button className="btn primary" onClick={propose}
              disabled={!canAsk || blocked || outOfRevisions || !!proposal}>
              <Icon name="code" size={15} /> {busy === "propose" ? "Measuring the patch…" : "Record this as a build to review"}
            </button>
            <button className="btn ghost" onClick={() => { setReport(null); setRefusal(""); }}>
              <Icon name="close" size={15} /> Not this
            </button>
          </div>
          <p className="muted small">Recording it writes nothing either: it diffs the patch against page v{version}
            and leaves it here for you to read, then Apply runs the same pipeline every other workspace change
            does.</p>
        </section>
      )}

      {err && !proposal && <div className="error" role="alert">{err}</div>}

      {proposal && (
        <section className="ve-plan stack">
          <div className="row wrap between">
            <h3>{proposal.headline}</h3>
            <span className={`pill ${proposal.safe_to_apply ? "ok" : "err"}`}>
              {proposal.safe_to_apply ? "no blocking risks"
                : `${proposal.impact?.counts?.errors || 1} blocking risk(s)`}
            </span>
          </div>
          <div className="row wrap">
            <span className="pill mono">{proposal.proposal.id}</span>
            <span className="pill">{proposal.proposal.patch.op} · {proposal.proposal.patch.file}</span>
            <span className={`pill ${TONE[proposal.overall]}`}>{proposal.overall_label}</span>
            <span className="pill ok">+{proposal.projection.lines_added}</span>
            <span className="pill err">-{proposal.projection.lines_removed}</span>
            {!!proposal.unchanged && <span className="pill warn">this patch changes nothing</span>}
            <span className="pill">{proposal.limits.revisions_left} revision(s) left</span>
          </div>
          <p className="muted small">{proposal.summary}</p>
          <div className="row wrap">
            <DiffModeToggle mode={mode} setMode={setMode} />
          </div>
          <dl className="ve-patch">
            <dt>Block</dt><dd className="mono">{proposal.proposal.patch.note}</dd>
            <dt>Find</dt><dd className="mono">{`“${proposal.proposal.patch.find_quote}…” — one place on v${proposal.base_version}`}</dd>
            <dt>Replace with</dt><dd className="mono">{`${proposal.proposal.patch.replace_bytes} bytes — the block for ${proposal.proposal.keys.length} feature(s)`}</dd>
          </dl>
          <p className="muted small">Only the feature block moves; the page’s own markup, copy and styling are
            untouched. {proposal.proposal.server
              ? "The server files below are written beside the page by the same apply, and rolled back with it if the page patch is refused."
              : "This set needs no server: it lives in the page alone."}</p>
          {Object.entries(proposal.diffs || {}).map(([name, d]) => (
            <div key={name} className="stack">
              <p className="muted small mono">{name} · +{d.added} -{d.removed}{d.truncated ? " · rows truncated" : ""}</p>
              <DiffBody rows={d.rows} side={d.side} mode={mode} />
            </div>
          ))}
          <div className="stack">
            <strong className="small">Source files this build ships</strong>
            <FileRows files={proposal.files} />
            <p className="muted small">Not written yet — Apply stages them with the page patch, and the
              sanitizer, the Chromium checks and the readiness score run over the page afterwards.</p>
          </div>
          {!!proposal.warnings?.length && (
            <ul className="ds-notes">{proposal.warnings.map((w, i) => (
              <li key={`pw${i}`}><Icon name="alert" size={14} /> {w}</li>))}</ul>
          )}
          <label>Why (optional, kept with the record)
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200}
              placeholder="Client needs the workshop desk online before the season starts"
              aria-label="Reason for this decision" />
          </label>
          <div className="row wrap">
            <button className="btn primary" onClick={apply}
              disabled={!editable || !!busy || !proposal.safe_to_apply || outOfRevisions}>
              <Icon name="check" size={15} /> {busy === "apply" ? "Building…" : "Apply and re-check"}
            </button>
            <button className="btn ghost" onClick={reject} disabled={!!busy}>
              <Icon name="close" size={15} /> {busy === "reject" ? "…" : "Reject"}
            </button>
          </div>
          <p className="muted small">Measured against page v{proposal.base_version}
            {!editable && " — applying needs the run back at the approval gate"}
            {blocked && " — the crew is working on this run now"}
            {proposal.safe_to_apply ? "" : " — a blocking risk means this patch is not applied, only recorded"}.
            {" "}Applying snapshots the whole file set first, so the feature is undoable.</p>
        </section>
      )}

      {!!undo?.can_undo && (
        <button className="btn ghost small" onClick={() => step()} disabled={!editable || !!busy}>
          <Icon name="undo" size={14} /> Undo the last recorded change (w{undo.next_undo})
        </button>
      )}

      <section className="stack ve-history">
        <div className="row between wrap">
          <h3>Feature builds on this run</h3>
          <Link className="muted small" to="/versions"><Icon name="book" size={13} /> Version history</Link>
        </div>
        {!status && !statusErr && <p className="muted small">Loading this run’s feature history…</p>}
        {status && !status.proposals.length && (
          <EmptyState icon="code" title="No feature proposals yet"
            text="Describe what the site must do, or pick from the catalog above. The record keeps the patch, the
              files it writes and the decision — whether you apply it, leave it, or turn it down." />
        )}
        <ul className="plan-list">
          {(status?.proposals || []).map((p) => (
            <li key={p.id} className={`plan-item ${p.status === "applied" ? "applied" : p.status === "rejected" ? "rejected" : "pending"}`}>
              <div className="row wrap between">
                <div className="row wrap">
                  <span className={`pill ${p.status === "applied" ? "ok" : p.status === "rejected" ? "err" : ""}`}>{p.status}</span>
                  <strong className="mono">{p.id}</strong>
                  <span className={`pill ${TONE[p.overall]}`}>{p.overall_label}</span>
                  <span className="pill">{(p.keys || []).length} feature(s)</span>
                  {!!p.server && <span className="pill">server source</span>}
                </div>
                <span className="muted small">{timeAgo(p.at)} · v{p.version}</span>
              </div>
              <p className="muted small">{(p.keys || []).map(labelOf).join(", ")}</p>
              <p className="muted small">{p.request || p.summary}</p>
              <p className="muted small mono">{(p.files || []).map((f) => f.name).join(", ")}
                {p.introduces?.length ? ` · ${p.introduces.length} new` : ""}
                {p.added?.length ? ` · ${p.added.length} pulled in` : ""}
                {p.present_before?.length ? ` · ${p.present_before.length} kept` : ""}
                {p.unchanged ? " · changed nothing" : ""} · +{p.lines_added} -{p.lines_removed}
                {p.result?.version ? ` · applied as v${p.result.version}` : ""}
                {p.result?.workspace_version ? ` · restores from w${p.result.workspace_version}` : ""}
                {p.result?.authored?.length ? ` · ${p.result.authored.length} source file(s) written` : ""}
                {!!p.result?.check_errors && ` · ${p.result.check_errors} check error(s)`}
                {!!p.result?.check_warnings && ` · ${p.result.check_warnings} check warning(s)`}
                {p.result?.readiness != null && ` · readiness ${p.result.readiness}`}
                {p.result?.sanitizer_removed ? ` · ${p.result.sanitizer_removed} markup item(s) stripped` : ""}
                {p.result?.reason ? ` · “${p.result.reason}”` : ""}
                {p.result?.error ? ` · ${p.result.error}` : ""}</p>
              {(p.status === "applied" && p.overall !== "generated") && (
                <p className="muted small">Applied, and still not live end to end:
                  {" "}{(p.features || []).filter((f) => f.status !== "generated").map((f) => `${f.label} — ${SHORT[f.status] || f.status}`).join("; ")}</p>
              )}
              {!!(p.warnings || []).length && (
                <ul className="ds-notes">{p.warnings.slice(0, 3).map((w, i) => (
                  <li key={`h${p.id}-${i}`}><Icon name="alert" size={14} /> {w}</li>))}</ul>
              )}
              {p.status === "applied" && !!p.result?.workspace_version && (
                <button className="btn ghost small" onClick={() => step(p.result.workspace_version)}
                  disabled={!editable || !!busy}>
                  <Icon name="redo" size={14} /> Restore the workspace from before this build
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
