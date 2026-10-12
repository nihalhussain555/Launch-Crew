/* Theme editing on a live run: the same customizer, measured against this page before it is written.

   The panel never claims a theme "was applied" on its own. `preview` is a read-only measurement of what
   these controls would write here, `propose` turns that into one `:root` patch and diffs it, and only
   `apply` hands it to the crew's pipeline — which snapshots first, sanitizes and re-checks in Chromium
   after, and records the result against the proposal. When the page hardcodes a property this theme
   changes, `unreached` says so and the panel refuses to pretend that part will move.

   The "in your own words" box is the same edit reached from a sentence: the server answers with the exact
   phrases it read, the control each one moved, and any phrase it refused. Loading those controls is not
   writing them — every claim of change below still comes from a measured, diffed, approved patch.
*/
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ContrastPanel, SWATCH_KEYS } from "./ThemeControls";
import { DiffBody, DiffModeToggle } from "./DiffView";
import EmptyState from "./EmptyState";
import Icon from "./Icon";
import ThemeControls from "./ThemeControls";
import { useThemeRegistry } from "../hooks/useThemeRegistry";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

/* A token this theme writes that the page never reads as a variable. The names come from the server, so
   this only explains them in the reader's language - an unknown variable is shown as it is. */
const TOKEN_LABEL = {
  "--bg": "page background", "--surface": "panel surface", "--text": "body text", "--muted": "muted text",
  "--primary": "primary colour", "--on-primary": "label on primary", "--secondary": "secondary colour",
  "--secondary-text": "label on secondary", "--accent": "accent", "--border": "hairline", "--band": "tinted band",
  "--radius": "corner radius", "--art-radius": "image corners", "--card-radius": "card corners",
  "--card-pad": "card padding", "--card-bg": "card fill", "--card-border": "card outline",
  "--card-shadow": "card shadow", "--card-blur": "card blur", "--btn-bg": "button fill",
  "--btn-fg": "button label", "--btn-border": "button outline", "--btn-radius": "button corners",
  "--btn-shadow": "button shadow", "--shadow": "shadow", "--shadow-strong": "raised shadow",
  "--line": "rule", "--focus-ring": "focus ring", "--space": "spacing", "--width": "container width",
  "--scale": "type scale", "--base": "body size", "--h1": "display size", "--h2": "heading size",
};

const hasFamily = (c) => !!(c && typeof c === "object" && c.family);

/* The control names a plain-English sentence lands on, in the reader's language. The phrases and their
   reasons come from the server's registry, so this table only translates a control key. */
const CONTROL_NAME = {
  family: "palette family", mode: "light or dark", pairing: "type pairing", scale: "type scale",
  density: "density", width: "container width", radius: "corner radius", shadow: "shadows",
  button: "button style", card: "card style", colors: "colours",
};
const RESET_TEXT = {
  colors: "A named family is a request for that palette, so this page's own six colours are replaced rather than kept.",
};

/** Measure, plan and apply a whole-site theme change on one run. */
export default function ThemeStudio({ runId, version, setRun, refresh, reload, working, editable, undo,
                                      externalAsk, onAskConsumed }) {
  const toast = useToast();
  const { reg } = useThemeRegistry();
  const [library, setLibrary] = useState(null);
  const [status, setStatus] = useState(null);
  const [controls, setControls] = useState(null);
  const [origin, setOrigin] = useState("project");   // project | saved | custom
  const [loadedId, setLoadedId] = useState("");
  const [preview, setPreview] = useState(null);
  const [previewErr, setPreviewErr] = useState("");
  const [measuring, setMeasuring] = useState(false);
  const [askText, setAskText] = useState("");
  const [ask, setAsk] = useState(null);
  const [askBusy, setAskBusy] = useState(false);
  const [askErr, setAskErr] = useState("");
  const [request, setRequest] = useState("");
  const [plan, setPlan] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [mode, setMode] = useState("unified");

  const loadStatus = useCallback(() => {
    if (!runId) { setStatus(null); return; }
    api.runTheme(runId).then((d) => setStatus(d)).catch(() => setStatus(null));
  }, [runId]);

  useEffect(() => { loadStatus(); }, [loadStatus, version]);
  useEffect(() => { api.listThemes().then(setLibrary).catch(() => setLibrary({ themes: [] })); }, []);

  // Start from the design this run already carries, so the swatches show what the page is drawn with now.
  useEffect(() => {
    if (!reg || controls || !status) return;
    if (hasFamily(status.theme)) setControls({ ...status.theme });
    else { setControls({ ...reg.default }); setOrigin("default"); }
  }, [reg, status, controls]);

  // Debounced measurement: a drag on a slider is one read of the page, not forty.
  useEffect(() => {
    if (!runId || !controls) return undefined;
    let live = true;
    setMeasuring(true);
    const t = setTimeout(() => {
      api.themePreview(runId, { theme: controls, base_version: version })
        .then((d) => { if (live) { setPreview(d); setPreviewErr(""); } })
        .catch((e) => { if (live) { setPreview(null); setPreviewErr(e.message); } })
        .finally(() => { if (live) setMeasuring(false); });
    }, 500);
    return () => { live = false; clearTimeout(t); };
  }, [runId, controls, version]);

  // A new page version invalidates a patch measured against the old one.
  useEffect(() => { setPlan(null); }, [version, runId]);

  const set = useCallback((patch) => { setControls((c) => ({ ...c, ...patch })); setOrigin("custom"); }, []);

  /* A sentence about the look of the whole site is matched onto controls by the server, which names the words
     it read and refuses the ones it cannot honour. Loading the controls is not writing them: the page only
     moves once this theme is measured, planned as a patch and applied. */
  const askWords = async (text) => {
    const sentence = String(text || "").trim();
    if (!sentence || !runId) return;
    setAskText(sentence); setAsk(null); setAskErr(""); setAskBusy(true);
    try {
      const d = await api.themeFromRequest(runId, { request: sentence, base_version: version });
      setAsk(d);
      setControls({ ...d.controls });
      setOrigin("custom");
      setRequest((cur) => (cur.trim() ? cur : sentence));
    } catch (ex) { setAskErr(ex.message); } finally { setAskBusy(false); }
  };

  // A sentence handed over from the visual editor is asked once, so a re-render cannot repeat the read.
  const handed = useRef("");
  useEffect(() => {
    if (!externalAsk || handed.current === externalAsk) return;
    handed.current = externalAsk;
    onAskConsumed?.();
    askWords(externalAsk);
  }, [externalAsk]);

  const themes = library?.themes || [];
  const loaded = themes.find((t) => t.id === loadedId);

  const pickSaved = (id) => {
    const t = themes.find((x) => x.id === id);
    if (!t) return;
    setControls({ ...t.controls });
    setLoadedId(id);
    setOrigin("saved");
    setErr("");
  };

  const backToProject = () => {
    if (!hasFamily(status?.theme)) return;
    setControls({ ...status.theme });
    setLoadedId("");
    setOrigin("project");
  };

  const reach = useMemo(() => {
    if (!preview) return null;
    return { wants: Object.keys(preview.variables || {}).length, declared: (preview.declared || []).length,
             reached: (preview.reached || []).length, unreached: preview.unreached || [] };
  }, [preview]);

  const propose = async () => {
    setBusy("plan"); setPlan(null); setErr("");
    try { setPlan(await api.themePropose(runId, { theme: controls, request: request.trim(), base_version: version })); }
    catch (ex) { setErr(ex.message); } finally { setBusy(""); }
  };

  const apply = async () => {
    setBusy("apply");
    try {
      setRun(await api.themeApply(runId, { id: plan.proposal.id, base_version: plan.base_version }));
      toast("Theme queued — the page is rebuilding and re-checking", "success");
      setPlan(null); setNote(""); setRequest("");
      await refresh();
      await reload();
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const reject = async () => {
    setBusy("reject");
    try {
      await api.themeReject(runId, { id: plan.proposal.id, reason: note.trim() });
      toast("Rejected — nothing was written to the workspace", "info");
      setPlan(null); setNote("");
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const step = async (w) => {
    setBusy(w ? `w${w}` : "undo");
    try {
      // the snapshot taken before that theme edit: restoring it puts the old design back, and is undoable too
      setRun(await (w ? api.wsRestore(runId, w, version) : api.wsUndo(runId, version)));
      toast(w ? `Restoring w${w}` : "Undoing the last recorded change", "info");
      setPlan(null);
      await refresh();
      await reload();
      loadStatus();
    } catch (ex) { toast(ex.message, "error"); } finally { setBusy(""); }
  };

  const blocked = !!status?.busy || working;
  const canPlan = !!controls && !!preview?.has_token_block && reach?.reached > 0 && !blocked && !busy;
  const originLabel = origin === "saved" && loaded ? `“${loaded.name || loaded.label}”`
    : origin === "custom" ? "edited here"
    : origin === "default" ? "registry default" : "this project’s own theme";

  return (
    <aside className="card stack ve-panel" aria-label="Theme studio">
      <div className="row between wrap">
        <h2>Theme studio</h2>
        <span className={`pill ${plan ? "warn" : preview ? "ok" : ""}`}>
          {plan ? "patch to review" : preview ? "measured on this page" : "measuring…"}
        </span>
      </div>

      <div className="row wrap">
        <span className="pill">page v{version}</span>
        <span className={`pill ${editable ? "ok" : ""}`}>{editable ? "at the approval gate" : "not editable now"}</span>
        {status && <span className="pill">{status.count}/{status.max} proposal(s)</span>}
        {status?.open && <span className="pill warn">{status.open_id} awaiting a decision</span>}
        {status && <span className="pill">{status.limits.revisions_left} revision(s) left</span>}
        <span className="pill" title="Where these controls came from">{originLabel}</span>
      </div>

      {!!themes.length && (
        <div className="row wrap ts-pick">
          <label className="ds-style-pick">
            <span className="muted small">Load a saved theme</span>
            <select value={loadedId} onChange={(e) => (e.target.value ? pickSaved(e.target.value) : backToProject())}
              disabled={!reg} aria-label="Saved theme to load">
              <option value="">— none —</option>
              {themes.map((t) => <option key={t.id} value={t.id}>{t.name || t.label} · {t.mode}</option>)}
            </select>
          </label>
          {!!loadedId && hasFamily(status?.theme) && (
            <button className="btn ghost small" onClick={backToProject} disabled={!!busy}>
              <Icon name="undo" size={14} /> Back to this project
            </button>
          )}
        </div>
      )}
      {!library && <p className="muted small">Reading your theme library…</p>}
      {!!library && !themes.length && (
        <p className="muted small">No saved themes yet — <Link to="/design">the Design System</Link> page can make one
          to reuse here and on future briefs. Tuning the controls below works without saving anything.</p>
      )}

      <section className="ts-ask stack">
        <div className="row between wrap">
          <h3>In your own words</h3>
          <span className="pill">{(reg?.requests?.phrases || []).length} phrase(s) understood</span>
        </div>
        <form className="row wrap ts-ask-bar" onSubmit={(e) => { e.preventDefault(); askWords(askText); }}>
          <input value={askText} onChange={(e) => setAskText(e.target.value)} maxLength={300}
            placeholder="Make the entire site look more premium." aria-label="Whole-site appearance request" />
          <button className="btn ghost" type="submit" disabled={!askText.trim() || askBusy || blocked}>
            <Icon name="sparkle" size={15} /> {askBusy ? "Reading the words…" : "Match to the controls"}
          </button>
        </form>
        <p className="muted small">Each phrase is read against this customizer's own controls — no model call, and a
          word it cannot honour is refused with its reason instead of being answered by a theme picked at random.
          Matching sets the controls below; the page still only moves through a measured patch you approve.</p>

        {askErr && (
          <div className="ve-refusal" role="status">
            <div className="row wrap"><Icon name="alert" size={15} /><strong>Nothing was matched</strong></div>
            <p className="muted small">{askErr}</p>
          </div>
        )}

        {ask && (
          <div className="ts-ask-out stack">
            <div className="row wrap between">
              <strong>{ask.summary}</strong>
              <span className="sw-row" aria-hidden="true">
                {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: ask.palette[k] }} />)}
              </span>
            </div>
            <ul className="ts-maps">
              {ask.matched.map((m) => (
                <li key={`${m.control}-${m.phrase}`}>
                  <div className="row wrap">
                    <span className="mono">“{m.phrase}”</span>
                    <Icon name="arrowRight" size={13} />
                    <span className="pill">{CONTROL_NAME[m.control] || m.control}</span>
                    <span className="pill ok">{m.label}</span>
                  </div>
                  <p className="muted small">{m.why}</p>
                </li>
              ))}
            </ul>
            {!!ask.resets?.length && (
              <p className="muted small">{ask.resets.map((r) => RESET_TEXT[r] || r).join(" ")}</p>
            )}
            {!!ask.conflicts?.length && (
              <ul className="ts-maps">
                {ask.conflicts.map((c, i) => (
                  <li key={`c-${c.control}-${i}`}>
                    <div className="row wrap"><span className="pill warn">two phrases, one control</span></div>
                    <p className="muted small">“{c.phrase}” names {CONTROL_NAME[c.control] || c.control}
                      (<span className="mono">{c.value}</span>) as well, but “{c.instead_phrase}”
                      (<span className="mono">{c.instead}</span>) outranks it in the table, so that is what these
                      controls carry.</p>
                  </li>
                ))}
              </ul>
            )}
            {!!ask.declined?.length && (
              <ul className="ts-maps">
                {ask.declined.map((d, i) => (
                  <li key={`d-${d.phrase}-${i}`}>
                    <div className="row wrap"><span className="mono">“{d.phrase}”</span>
                      <span className="pill warn">not changed</span></div>
                    <p className="muted small">{d.reason}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {!!(reg?.requests?.phrases || []).length && (
          <details className="ts-ask-lex">
            <summary>The words it reads</summary>
            <div className="row wrap">
              {reg.requests.phrases.map((p, i) => (
                <button type="button" key={`lex-${i}`} className="pill" onClick={() => setAskText(p.phrase)}
                  title={`${CONTROL_NAME[p.control] || p.control}: ${p.label}`}>{p.phrase}</button>
              ))}
            </div>
            {!!reg.requests.declined?.length && (
              <ul className="ts-maps">
                {reg.requests.declined.map((d, i) => (
                  <li key={`ld-${i}`}>
                    <div className="row wrap"><span className="mono">“{d.phrase}”</span>
                      <span className="pill warn">refused</span></div>
                    <p className="muted small">{d.reason}</p>
                  </li>
                ))}
              </ul>
            )}
          </details>
        )}
      </section>

      {!reg || !controls ? <div className="card skeleton" style={{ height: 220 }} aria-busy="true" /> : (
        <ThemeControls reg={reg} controls={controls} resolved={preview?.theme} onChange={set}
          disabled={!!busy || blocked} />
      )}

      {measuring && <p className="muted small" role="status">Measuring these tokens against page v{version}…</p>}
      {previewErr && !preview && (
        <div className="ve-refusal" role="status">
          <div className="row wrap"><Icon name="alert" size={15} /><strong>This page can’t be measured</strong></div>
          <p className="muted small">{previewErr}</p>
        </div>
      )}

      {preview && (
        <>
          <div className="ve-sel stack">
            <div className="row wrap between">
              <strong>{preview.summary}</strong>
              <span className="sw-row" aria-hidden="true">
                {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: preview.palette[k] }} />)}
              </span>
            </div>
            {reach && (
              <div className="row wrap">
                <span className="pill">{reach.wants} token(s) written</span>
                <span className="pill ok">{reach.reached} reached here</span>
                <span className="pill">{reach.declared} declared in the block</span>
                {!!reach.unreached.length && <span className="pill warn">{reach.unreached.length} hardcoded</span>}
              </div>
            )}
            {!preview.has_token_block ? (
              <p className="error" role="alert">This page declares no <code className="inline-code">:root</code> block,
                so it has no design tokens to change — restyling it would mean rewriting its rules one by one, which a
                theme edit deliberately does not do.</p>
            ) : (
              <>
                <p className="muted small">The patch rewrites this page’s token block only. A property the block declares,
                  or one a rule outside it reads with <code className="inline-code">var()</code>, moves with the theme;
                  a property the page hardcodes is listed below instead of being quietly patched.</p>
                {!!reach?.unreached.length && (
                  <ul className="ve-refs">
                    {reach.unreached.map((v) => (
                      <li key={v}>
                        <div className="row wrap"><span className="mono">{v}</span>
                          <span className="pill warn">stays as the page has it</span></div>
                        <p className="muted small">{TOKEN_LABEL[v] || v}: no rule on this page reads it as a token,
                          so changing the theme cannot reach it.</p>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
          <ContrastPanel contrast={preview.contrast} notes={preview.notes} />
        </>
      )}

      {controls && preview?.has_token_block && (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); propose(); }}>
          <label>What should this theme do for the site?
            <input value={request} onChange={(e) => setRequest(e.target.value)} maxLength={300}
              placeholder="Feel more premium: deeper dark, softer corners, calmer shadows"
              aria-label="Reason for this theme change" />
          </label>
          <p className="muted small">This costs no model call and writes nothing: the patch is computed from the theme,
            then measured and diffed against page v{version} for you to read.</p>
          <button className="btn primary" type="submit" disabled={!canPlan}>
            <Icon name="sparkle" size={15} /> {busy === "plan" ? "Planning the token patch…" : "Plan this theme"}
          </button>
          {blocked && <p className="muted small">The crew is working on this run — planning is free, but a patch measured
            now may not match the page once it settles.</p>}
          {!!reach && reach.reached === 0 && preview?.has_token_block && (
            <p className="muted small">Every token this theme writes is already correct on this page, so there is nothing
            for a patch to change. Move a colour or a control, or pick a different theme.</p>
          )}
        </form>
      )}

      {err && !plan && <div className="error" role="alert">{err}</div>}

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
            <span className="pill ok">{plan.reaches} token(s) move</span>
            <span className="pill">{plan.replaced.length} rewritten</span>
            {!!plan.added.length && <span className="pill">{plan.added.length} added</span>}
            {!!plan.kept.length && <span className="pill">{plan.kept.length} already matched</span>}
            {!!plan.unreached.length && <span className="pill warn">{plan.unreached.length} unreachable</span>}
            <span className="pill">{plan.limits.revisions_left} revision(s) left</span>
          </div>
          <p className="muted small">{plan.proposal.summary}</p>
          <div className="row wrap">
            {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: plan.theme.palette[k] }} />)}
            <DiffModeToggle mode={mode} setMode={setMode} />
          </div>
          <dl className="ve-patch">
            <dt>Block</dt><dd className="mono">{plan.patch.note}</dd>
            <dt>Find</dt><dd className="mono">{`${plan.patch.find.length} characters — the :root block at v${plan.base_version}`}</dd>
            <dt>Replace with</dt><dd className="mono">{`${plan.patch.replace.length} characters — the same block, ${plan.reaches} value(s) written`}</dd>
          </dl>
          <p className="muted small">Only the token block is rewritten; the components’ CSS is untouched, which is why a
            diff this small can move the whole site.</p>
          {Object.entries(plan.diffs || {}).map(([name, d]) => (
            <div key={name} className="stack">
              <p className="muted small mono">{name} · +{d.added} -{d.removed}{d.truncated ? " · rows truncated" : ""}</p>
              <DiffBody rows={d.rows} side={d.side} mode={mode} />
            </div>
          ))}
          <label>Why (optional, kept with the record)
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200}
              placeholder="Client wants a darker, calmer look" aria-label="Reason for this decision" />
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
            {working ? " — it is working now." : "."} Applying snapshots the page first, so the theme is undoable.</p>
        </section>
      )}

      {!!undo?.can_undo && (
        <button className="btn ghost small" onClick={() => step()} disabled={!editable || !!busy}>
          <Icon name="undo" size={14} /> Undo the last recorded change (w{undo.next_undo})
        </button>
      )}

      <section className="stack ve-history">
        <div className="row between wrap">
          <h3>Theme edits on this run</h3>
          <Link className="muted small" to="/design">Design System</Link>
        </div>
        {!status && <p className="muted small">Loading this run’s theme history…</p>}
        {status && !status.proposals.length && (
          <EmptyState icon="palette" title="No theme proposals yet"
            text="Tune the controls and plan a theme — the record keeps the patch, its reach and the decision, whether you apply it or leave it unread." />
        )}
        <ul className="plan-list">
          {(status?.proposals || []).map((p) => (
            <li key={p.id} className={`plan-item ${p.status === "applied" ? "applied" : p.status === "rejected" ? "rejected" : "pending"}`}>
              <div className="row wrap between">
                <div className="row wrap">
                  <span className={`pill ${p.status === "applied" ? "ok" : p.status === "rejected" ? "err" : ""}`}>{p.status}</span>
                  <strong className="mono">{p.id}</strong>
                  <span className="pill">{p.theme?.family} · {p.theme?.mode}</span>
                  <span className="pill">{p.reaches} token(s)</span>
                </div>
                <span className="muted small">{timeAgo(p.at)} · v{p.version}</span>
              </div>
              <div className="row wrap" aria-hidden="true">
                {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: p.palette?.[k] }} />)}
              </div>
              <p className="muted small">{p.request || p.summary}</p>
              <p className="muted small mono">{p.files?.join(", ")} · {p.replaced?.length} rewritten
                {p.added?.length ? ` · ${p.added.length} added` : ""}
                {p.unreached?.length ? ` · ${p.unreached.length} unreachable` : ""} · +{p.lines_added} -{p.lines_removed}
                {p.result?.version ? ` · applied as v${p.result.version}` : ""}
                {p.result?.workspace_version ? ` · restores from w${p.result.workspace_version}` : ""}
                {p.result?.reason ? ` · “${p.result.reason}”` : ""}
                {p.result?.error ? ` · ${p.result.error}` : ""}</p>
              {!!(p.notes || []).length && (
                <ul className="ds-notes">{p.notes.map((n) => <li key={n}><Icon name="alert" size={14} /> {n}</li>)}</ul>
              )}
              {p.status === "applied" && !!p.result?.workspace_version && (
                <button className="btn ghost small" onClick={() => step(p.result.workspace_version)}
                  disabled={!editable || !!busy}>
                  <Icon name="redo" size={14} /> Restore the page from before this theme
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
