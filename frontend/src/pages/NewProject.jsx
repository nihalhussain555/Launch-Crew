import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import StylePicker from "../components/StylePicker";
import TagInput from "../components/TagInput";
import WizardStepper from "../components/WizardStepper";
import { EXAMPLES } from "../constants";
import { useStartRun } from "../hooks/useStartRun";
import { useToast } from "../toast";

// The same limits app/agents/schemas.py SiteSpec enforces, so the wizard refuses what the API would
// refuse instead of letting a run die on a 422 after the user has filled in six steps.
const LIMITS = { idea: 500, audience: 160, tone: 120, features: 10, pages: 8, sections: 12, compare: 4,
                 feature_keys: 16 };
const PAGE_SLUG = /^[a-z0-9][a-z0-9-]{0,23}$/;
const HEX = /^#[0-9a-f]{6}$/;
const SWATCHES = ["background", "surface", "primary", "accent", "text"];
// The catalog's three honest states, in the words a brief uses. A pick never upgrades one of them.
const STATUS_WORD = { generated: "works in the page", scaffold: "server you start",
                      "needs-external-setup": "needs your keys" };
const DRAFT_KEY = "lc_wizard_draft";

const STEPS = [
  { id: "idea", title: "Idea" },
  { id: "type", title: "Site type" },
  { id: "audience", title: "Audience & tone" },
  { id: "content", title: "Content" },
  { id: "style", title: "Design style" },
  { id: "review", title: "Review" },
];
const STEP_KEYS = [["idea"], ["type"], ["audience", "tone"], ["features", "pages", "sections", "feature_keys"], ["style", "color", "theme"], []];

const EMPTY = { idea: "", business_type: "other", audience: "", tone: "", features: [], pages: [],
                sections: [], style: "", color: "", mode: "single", compare: [], theme: null, feature_keys: [],
                template: "" };

function loadDraft(params) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}") || {}; } catch { saved = {}; }
  const d = { ...EMPTY, ...saved };
  // A template card hands over its key; the brief it stands for is read back from the registry below
  // rather than passed through the URL, so a card cannot prefill a composition the builder no longer has.
  const template = params.get("template");
  if (template) d.template = template;
  // A template or dashboard link can prefill the brief; what it passes wins over the stored draft.
  for (const key of ["idea", "business_type", "audience", "tone", "style", "color"]) {
    const fromUrl = params.get(key === "business_type" ? "business" : key);
    if (fromUrl) d[key] = fromUrl;
  }
  // A template card knows which sections it asks for; without this the prefilled brief would silently
  // launch a different page than the card showed.
  const sections = (params.get("sections") || "").split(",").map((s) => s.trim()).filter(Boolean);
  if (sections.length) d.sections = Array.from(new Set(sections)).slice(0, LIMITS.sections);
  // A Design System card hands over only an id: the controls live on the library row, so the pick is
  // resolved once the library loads rather than being invented from the id.
  const theme = params.get("theme");
  if (theme) d.theme = { id: theme, name: "", controls: null };
  return d;
}

function briefErrors(d, reg, themes, caps) {
  const e = {};
  const idea = d.idea.trim();
  if (idea.length < 5) e.idea = "Tell the crew a bit more - at least 5 characters.";
  else if (idea.length > LIMITS.idea) e.idea = `Keep the idea under ${LIMITS.idea} characters.`;
  if (reg && !reg.business_types.some((b) => b.key === d.business_type))
    e.type = "Choose a site type, or leave it on “Not sure yet”.";
  if (d.audience.length > LIMITS.audience) e.audience = `Audience must be under ${LIMITS.audience} characters.`;
  if (d.tone.length > LIMITS.tone) e.tone = `Tone must be under ${LIMITS.tone} characters.`;
  if (d.features.length > LIMITS.features) e.features = `Up to ${LIMITS.features} requested features.`;
  const badPage = d.pages.find((p) => !PAGE_SLUG.test(p));
  if (badPage) e.pages = `“${badPage}” is not a page name: lower-case letters, digits or hyphens only.`;
  if (d.pages.length > LIMITS.pages) e.pages = `Up to ${LIMITS.pages} pages.`;
  if (d.sections.length > LIMITS.sections) e.sections = `Up to ${LIMITS.sections} extra sections.`;
  // A feature key is a build the crew has source for, so a pick that the catalog no longer carries is
  // refused here rather than 422ing the whole brief at the API.
  if (d.feature_keys.length > LIMITS.feature_keys) e.feature_keys = `Up to ${LIMITS.feature_keys} features.`;
  else if (caps && d.feature_keys.some((k) => !caps.capabilities.some((c) => c.key === k)))
    e.feature_keys = "One of those features is not in the catalog any more - re-pick the list below.";
  if (d.style && reg && !reg.styles.some((s) => s.key === d.style))
    e.style = "That style is not in the registry - pick one below or leave it to the crew.";
  if (d.mode === "compare" && d.compare.length < 2) e.style = `Pick ${2} to ${LIMITS.compare} styles to compare.`;
  if (d.color && !HEX.test(d.color)) e.color = "A preferred colour is a hex value like #4f46e5, or nothing.";
  // Waiting on the library is a real state, not an error the user made - but launching without the
  // controls would silently store an empty theme, which is worse than a brief that cannot proceed yet.
  if (d.theme && !d.theme.controls && themes) e.theme = "That theme is not in your library - pick one below or leave it to the crew.";
  else if (d.theme && !d.theme.controls) e.theme = "Reading that theme from your library…";
  return e;
}

export default function NewProject() {
  const nav = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  const [draft, setDraft] = useState(() => loadDraft(params));
  const [restored] = useState(() => {
    if (params.get("idea")) return false;                 // a prefilled brief is not a restored draft
    try { return !!localStorage.getItem(DRAFT_KEY); } catch { return false; }
  });
  const [step, setStep] = useState(0);
  // An empty brief is not an error the user has made yet, so a step only explains itself once they try
  // to leave it. Cleared on every step change.
  const [tried, setTried] = useState(false);
  const go = (i) => { setTried(false); setStep(i); };
  const [reloadKey, setReloadKey] = useState(0);
  const [reg, setReg] = useState(null);
  const [regErr, setRegErr] = useState("");
  const [resolved, setResolved] = useState(null);
  const [resolveErr, setResolveErr] = useState("");
  const [resolving, setResolving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [startErr, setStartErr] = useState("");
  const [themes, setThemes] = useState(null);        // the user's saved themes; null until the library answers
  const [themeNote, setThemeNote] = useState("");     // what happened to a theme handed over by id
  const [caps, setCaps] = useState(null);             // the feature catalog; null until the API answers
  const [capErr, setCapErr] = useState("");           // why no feature could be offered
  const [templateNote, setTemplateNote] = useState("");  // what happened to a card handed over by key
  const appliedTemplate = useRef("");
  const { start, busy: starting } = useStartRun();

  const set = useCallback((patch) => setDraft((d) => ({ ...d, ...patch })), []);
  const mode = draft.mode;
  const setMode = (next) => set({ mode: next });
  const spec = useMemo(() => ({
    business_type: draft.business_type, audience: draft.audience.trim(), pages: draft.pages,
    style: draft.mode === "compare" ? "" : draft.style, color: draft.color.trim().toLowerCase(),
    features: draft.features, tone: draft.tone.trim(), sections: draft.sections,
    theme: draft.theme?.controls || {}, template: draft.template,
  }), [draft]);
  const errors = useMemo(() => briefErrors(draft, reg, themes), [draft, reg, themes]);
  const stepBad = (i) => STEP_KEYS[i].some((k) => errors[k]);
  const ready = useMemo(() => Object.keys(errors).length === 0, [errors]);

  const fetchRegistry = useCallback(() => {
    setRegErr("");
    setReg(null);
    api.styles().then(setReg).catch((e) => setRegErr(e.message));
  }, []);
  useEffect(fetchRegistry, [fetchRegistry]);

  // The theme library is separate from the style registry: a brief may name a saved theme, and the only
  // place its controls exist is the library row. An unreachable library is a missing optional pick, not
  // a broken brief, so it degrades to "no theme" with the reason shown.
  const fetchThemes = useCallback(() => {
    setThemes(null);
    api.listThemes().then((d) => setThemes(d.themes || [])).catch((e) => { setThemes([]); setThemeNote(e.message); });
  }, []);
  useEffect(fetchThemes, [fetchThemes]);

  // The feature picker draws from the same catalog the builder writes from, so a brief can only ever ask
  // for source that exists. A draft saved before a feature was removed from that catalog is corrected by
  // dropping the key it no longer has - the picks it can still honour are kept.
  const fetchCaps = useCallback(() => {
    setCaps(null); setCapErr("");
    api.capabilities().then(setCaps).catch((e) => { setCaps(null); setCapErr(e.message); });
  }, []);
  useEffect(fetchCaps, [fetchCaps]);

  useEffect(() => {
    if (!caps || !draft.feature_keys.length) return;
    const known = draft.feature_keys.filter((k) => caps.capabilities.some((c) => c.key === k));
    if (known.length !== draft.feature_keys.length) set({ feature_keys: known });
  }, [caps, draft.feature_keys, set]);

  useEffect(() => {
    if (!themes || !draft.theme || draft.theme.controls) return;
    const found = themes.find((t) => t.id === draft.theme.id);
    if (found) {
      set({ theme: { id: found.id, name: found.name, controls: found.controls } });
      setThemeNote(`“${found.name}” loaded from your Design System.`);
    } else {
      set({ theme: null });
      setThemeNote("That theme is no longer in your library, so this brief will use the style's own palette.");
    }
  }, [themes, draft.theme, set]);

  // A gallery card arrives as a key, the same way a Design System card arrives as an id: the brief it
  // stands for is read back from the registry, so the wizard cannot prefill a composition the builder no
  // longer has. Applied once - after that the owner's edits are the brief, not the card.
  useEffect(() => {
    const key = params.get("template");
    if (!key || appliedTemplate.current === key) return undefined;
    appliedTemplate.current = key;
    let dead = false;
    api.templateDetail(key).then((d) => {
      if (dead) return;
      const s = d.spec;
      set({ idea: d.template.idea, business_type: s.business_type, audience: s.audience, tone: s.tone,
            features: s.features, pages: s.pages, sections: s.sections.slice(0, LIMITS.sections),
            style: s.style, color: s.color, feature_keys: s.feature_keys, template: s.template });
      setTemplateNote(`${d.template.label} loaded from the gallery. Every step is still yours to change.`);
    }).catch((e) => {
      if (dead) return;
      appliedTemplate.current = "";
      set({ template: "" });
      setTemplateNote(`${e.message} - this brief starts empty instead.`);
    });
    return () => { dead = true; };
  }, [params, set]);

  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...draft, mode })); } catch { /* storage full or blocked */ }
  }, [draft, mode]);

  // The review step shows what the server would actually store, so nothing here is a preview of a lie.
  useEffect(() => {
    if (step !== STEPS.length - 1 || !ready || !reg) return undefined;
    let dead = false;
    setResolving(true);
    setResolveErr("");
    api.resolveBrief(spec)
      .then((r) => { if (!dead) setResolved(r); })
      .catch((e) => { if (!dead) { setResolved(null); setResolveErr(e.message); } })
      .finally(() => { if (!dead) setResolving(false); });
    return () => { dead = true; };
  }, [step, spec, ready, reg, reloadKey]);

  const styleOf = (key) => (reg?.styles || []).find((s) => s.key === key) || null;
  const business = (reg?.business_types || []).find((b) => b.key === draft.business_type) || null;
  const pickedCaps = useMemo(() => (caps?.capabilities || []).filter((c) => draft.feature_keys.includes(c.key)),
    [caps, draft.feature_keys]);
  const picksWaiting = pickedCaps.filter((c) => c.status !== "generated");

  const pickBusiness = (b) => {
    // A style chosen in step 5 is kept; the site type only fills that choice in while it is still empty.
    set(!draft.style && b.style ? { business_type: b.key, style: b.style } : { business_type: b.key });
  };

  const launch = async () => {
    setStartErr("");
    if (!ready) {
      // The last step has no fields of its own, so send them to the answer that needs fixing.
      const i = STEP_KEYS.findIndex((ks) => ks.some((k) => errors[k]));
      if (i >= 0) setStep(i);
      setTried(true);
      return;
    }
    if (mode === "compare") {
      setBusy(true);
      try {
        const p = await api.createProject(draft.idea.trim(), spec);
        const res = await api.compareStyles(p.id, draft.compare);
        try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clean */ }
        toast(`${res.runs.length} variations are being built from this brief.`, "success");
        nav(`/runs/${res.runs[0].run_id}`);
      } catch (e) {
        setStartErr(e.message);
      } finally {
        setBusy(false);
      }
      return;
    }
    const ok = await start(draft.idea.trim(), spec);
    if (ok) { try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clean */ } }
  };

  const clearDraft = () => {
    setDraft(EMPTY);
    setMode("single");
    setTried(false);
    setStep(0);
    appliedTemplate.current = "";
    setTemplateNote("");
    try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to clean */ }
    toast("Draft cleared.", "success");
  };

  if (regErr) {
    return (
      <>
        <div className="page-head"><div><h1>New project</h1><p className="muted">The creation brief needs the design registry.</p></div></div>
        <ErrorState title="The design registry could not be loaded" message={regErr} retry={fetchRegistry} back="/dashboard" />
      </>
    );
  }

  const compareList = draft.compare.map((k) => styleOf(k)).filter(Boolean);
  const chosen = styleOf(draft.style);
  const palette = (chosen || compareList[0] || reg?.styles?.[0])?.palette || {};

  return (
    <>
      <div className="page-head">
        <div>
          <h1>New project</h1>
          <p className="muted">Six short steps. The answers are stored on the project and steer every run it starts.</p>
        </div>
        <Link to="/templates" className="btn ghost"><Icon name="sparkle" size={15} /> Start from a template</Link>
      </div>

      {templateNote && (
        <div className="card" role="status">
          <span className="muted small">{templateNote}</span>
        </div>
      )}

      {restored && draft.idea.trim() && (
        <div className="card" role="status">
          <div className="row between wrap">
            <span className="muted small">Your unfinished brief was restored from this browser.</span>
            <button className="btn ghost small" onClick={clearDraft}><Icon name="close" size={14} /> Discard draft</button>
          </div>
        </div>
      )}

      <WizardStepper steps={STEPS} current={step} onJump={go} />

      <section className="card wiz-body" aria-live="polite">
        <header className="wiz-head">
          <h2>{STEPS[step].title}</h2>
          <span className="muted small">Step {step + 1} of {STEPS.length}</span>
        </header>

        {!reg ? (
          <div className="stack" aria-busy="true">
            <div className="muted small">Loading the design registry…</div>
            {[0, 1, 2].map((i) => <div key={i} className="card skeleton" style={{ height: 96 }} />)}
          </div>
        ) : step === 0 ? (
          <div className="stack">
            <label htmlFor="wiz-idea">What are you launching?</label>
            <textarea id="wiz-idea" rows={4} maxLength={LIMITS.idea} value={draft.idea} data-autofocus
              placeholder="Describe the product and who it is for in a sentence or two…"
              onChange={(e) => set({ idea: e.target.value })} />
            <div className="row wrap">
              {EXAMPLES.map((x) => <button key={x} type="button" className="chip" onClick={() => set({ idea: x })}>{x}</button>)}
            </div>
            <div className="row between wrap">
              <span className="muted small">{draft.idea.trim().length}/{LIMITS.idea}</span>
              <span className="muted small">One idea per project - the crew writes one page from it.</span>
            </div>
          </div>
        ) : step === 1 ? (
          <div className="stack">
            <p className="muted">This decides the pages and sections the crew plans for, and suggests a style you can still change in step 5.</p>
            <div className="biz-grid" role="group" aria-label="Site type">
              {reg.business_types.map((b) => {
                const on = draft.business_type === b.key;
                return (
                  <button type="button" key={b.key} className={`biz-card card ${on ? "on" : ""}`} aria-pressed={on}
                    onClick={() => pickBusiness(b)}>
                    <strong>{b.label}</strong>
                    <span className="small muted">Pages: {b.pages.join(", ")}</span>
                    {(b.sections || []).length > 0 && <span className="row wrap">{b.sections.map((s) => <span key={s} className="chip">{s}</span>)}</span>}
                    <span className="small">Suggested style: {styleOf(b.style)?.label || "the crew's choice"}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : step === 2 ? (
          <div className="stack">
            <div className="field">
              <label htmlFor="wiz-audience">Who is it for? <span className="muted small">optional</span></label>
              <input id="wiz-audience" maxLength={LIMITS.audience} value={draft.audience}
                placeholder="night-shift nurses, independent landlords…" onChange={(e) => set({ audience: e.target.value })} />
              <span className="muted small">{draft.audience.length}/{LIMITS.audience}</span>
            </div>
            <div className="field">
              <label htmlFor="wiz-tone">Tone of voice <span className="muted small">optional</span></label>
              <input id="wiz-tone" maxLength={LIMITS.tone} value={draft.tone} placeholder="calm, practical, no hype"
                onChange={(e) => set({ tone: e.target.value })} />
              <div className="row wrap">
                {["calm and practical", "friendly and warm", "sharp and professional", "playful"].map((t) => (
                  <button key={t} type="button" className={`chip ${draft.tone === t ? "on" : ""}`}
                    aria-pressed={draft.tone === t} onClick={() => set({ tone: t })}>{t}</button>
                ))}
              </div>
              <span className="muted small">{draft.tone.length}/{LIMITS.tone}</span>
            </div>
            <p className="muted small">Leave either blank and the Researcher and Strategist work out the audience from the idea itself.</p>
          </div>
        ) : step === 3 ? (
          <div className="stack">
            <TagInput id="wiz-features" label="What must it do?" max={LIMITS.features}
              placeholder="recurring reminders, offline mode" hint="Plain words. Each one is read as a feature the page should show."
              values={draft.features} onChange={(v) => set({ features: v })} />
            <TagInput id="wiz-pages" label="Pages" max={LIMITS.pages} placeholder="home, pricing, about"
              hint={`Lower-case, hyphens, up to 24 characters. Empty = ${business ? business.pages.join(", ") : "the site type's usual pages"}.`}
              values={draft.pages} onChange={(v) => set({ pages: v })} clean={(v) => v.toLowerCase()}
              errorFor={(v) => (PAGE_SLUG.test(v) ? "" : "Use lower-case letters, digits or hyphens only.")} />
            <div className="field">
              <span className="side-label">Sections on the page</span>
              <p className="muted small">Always built: {reg.sections.always.join(", ")}. Choose up to {LIMITS.sections} more.</p>
              <div className="row wrap" role="group" aria-label="Extra sections">
                {reg.sections.optional.map((s) => {
                  const on = draft.sections.includes(s);
                  return (
                    <button key={s} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on}
                      disabled={!on && draft.sections.length >= LIMITS.sections}
                      onClick={() => set({ sections: on ? draft.sections.filter((x) => x !== s) : [...draft.sections, s] })}>
                      {on && <Icon name="check" size={12} />} {s}
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="field">
              <span className="side-label">Features to build</span>
              <p className="muted small">Real source, not a wish list: each pick writes its panel into the page and
                its server, schema and setup notes beside it. Nothing is generated from this tick — the brief carries
                the request, and the Feature studio in the Code Workspace measures the build and shows you the patch
                before anything is applied.</p>
              {caps === null && (
                <span className="muted small" role="status">{capErr ? `The feature catalog could not be read: ${capErr}`
                  : "Reading the feature catalog…"}</span>
              )}
              <div className="row wrap" role="group" aria-label="Features to build on this site">
                {(caps?.capabilities || []).map((c) => {
                  const on = draft.feature_keys.includes(c.key);
                  return (
                    <button key={c.key} type="button" className={`chip ${on ? "on" : ""}`} aria-pressed={on}
                      title={`${c.blurb} — ${c.status_label}`}
                      disabled={!on && draft.feature_keys.length >= LIMITS.feature_keys}
                      onClick={() => set({ feature_keys: on ? draft.feature_keys.filter((k) => k !== c.key)
                        : [...draft.feature_keys, c.key] })}>
                      {on && <Icon name="check" size={12} />} {c.label}
                    </button>
                  );
                })}
              </div>
              <span className="muted small">
                {draft.feature_keys.length}/{LIMITS.feature_keys} chosen.
                {picksWaiting.length
                  ? ` ${picksWaiting.length} of them need an account or your own server started - the studio names exactly what.`
                  : pickedCaps.length
                    ? " Everything picked here works in the published page once it is built."
                    : ""}
                {" "}Leave them all off and ask in your own words later.
              </span>
              {!!draft.feature_keys.length && (
                <button type="button" className="btn ghost small" onClick={() => set({ feature_keys: [] })}>
                  <Icon name="undo" size={14} /> Clear the picks
                </button>
              )}
            </div>
          </div>
        ) : step === 4 ? (
          <div className="stack">
            <div className="row between wrap">
              <div className="seg" role="group" aria-label="One style or a comparison">
                <button type="button" className={mode === "single" ? "on" : ""} aria-pressed={mode === "single"}
                  onClick={() => setMode("single")}>One style</button>
                <button type="button" className={mode === "compare" ? "on" : ""} aria-pressed={mode === "compare"}
                  onClick={() => setMode("compare")}>Compare 2–4</button>
              </div>
              <span className="muted small">Each comparison is a full run: same crew, same checks, one page per style.</span>
            </div>

            {mode === "single" && !draft.style && (
              <EmptyState icon="sparkle" title="No style chosen yet"
                text="Pick one below, or leave it to the crew - the run then gets a style seeded from its own id." />
            )}

            <StylePicker styles={reg.styles} mode={mode} value={draft.style} values={draft.compare}
              notes={reg.vocabulary} max={LIMITS.compare}
              onChange={(next) => set(mode === "single" ? { style: next } : { compare: next })} />

            {mode === "single" && draft.style && (
              <button type="button" className="btn ghost small" onClick={() => set({ style: "" })}>
                <Icon name="undo" size={14} /> Let the crew choose
              </button>
            )}

            <div className="field">
              <label htmlFor="wiz-color">Preferred colour <span className="muted small">optional</span></label>
              <div className="row wrap">
                <input id="wiz-color" maxLength={9} value={draft.color} placeholder="#4f46e5"
                  onChange={(e) => set({ color: e.target.value })} style={{ maxWidth: 180 }} />
                {["primary", "accent"].map((k) => palette[k] && (
                  <button key={k} type="button" className="btn small" onClick={() => set({ color: palette[k] })}>
                    <span className="sw" style={{ background: palette[k] }} aria-hidden="true" /> {k} {palette[k]}
                  </button>
                ))}
                {draft.color && <button type="button" className="btn ghost small" onClick={() => set({ color: "" })}>Clear</button>}
              </div>
              <span className="muted small">
                Used as the page's main colour if it can pass WCAG AA contrast; the review step reports what happened to it.
              </span>
            </div>

            <div className="field">
              <div className="row between wrap">
                <label htmlFor="wiz-theme">Theme <span className="muted small">optional</span></label>
                <Link to="/design" className="muted small"><Icon name="sliders" size={13} /> Design System</Link>
              </div>
              {themes === null ? (
                <span className="muted small">Reading your saved themes…</span>
              ) : themes.length === 0 ? (
                <span className="muted small">You have no saved themes yet. The page is then drawn in the
                  style's own palette — <Link to="/design">the Design System</Link> can save one to reuse here.</span>
              ) : (
                <>
                  <select id="wiz-theme" value={draft.theme?.id || ""} aria-label="Saved theme for this brief"
                    onChange={(e) => {
                      const t = themes.find((x) => x.id === e.target.value);
                      set({ theme: t ? { id: t.id, name: t.name, controls: t.controls } : null });
                    }}>
                    <option value="">No theme — use the style’s own palette</option>
                    {themes.map((t) => <option key={t.id} value={t.id}>{t.name} — {t.summary}</option>)}
                  </select>
                  {draft.theme && (
                    <div className="row wrap" aria-hidden="true">
                      {["background", "surface", "text", "primary", "secondary", "accent"]
                        .map((k) => <span key={k} className="sw" style={{ background: draft.theme.controls.colors?.[k] }} />)}
                    </div>
                  )}
                </>
              )}
              {themeNote && <span className="muted small" role="status">{themeNote}</span>}
              <span className="muted small">A theme sets colour, type, spacing, corners, shadows and density
                as design tokens. The style above still decides the layout — a theme cannot change it.</span>
            </div>
          </div>
        ) : (
          <div className="stack">
            {resolveErr && <ErrorState title="The brief could not be checked" message={resolveErr}
              retry={() => setReloadKey((k) => k + 1)} back="/dashboard" />}
            {resolving && <div className="card skeleton" style={{ height: 140 }} aria-busy="true" />}
            {resolved && (
              <div className="stack review">
                <div className="set-rows">
                  <div className="set-row"><span className="set-key">Idea</span><span className="set-val">{draft.idea.trim()}</span></div>
                  <div className="set-row"><span className="set-key">Site type</span><span className="set-val">{business?.label || draft.business_type}</span></div>
                  <div className="set-row"><span className="set-key">Audience</span><span className="set-val">{draft.audience.trim() || "worked out by the Researcher"}</span></div>
                  <div className="set-row"><span className="set-key">Tone</span><span className="set-val">{draft.tone.trim() || "no preference"}</span></div>
                  <div className="set-row"><span className="set-key">Requested features</span><span className="set-val">{draft.features.join(", ") || "the crew's reading of the idea"}</span></div>
                  <div className="set-row">
                    <span className="set-key">Features to build</span>
                    <span className="set-val">
                      {pickedCaps.length
                        ? pickedCaps.map((c) => `${c.label} — ${STATUS_WORD[c.status] || c.status}`).join(", ")
                        : "none ticked - ask for them in the Feature studio once the page is waiting for approval"}
                    </span>
                  </div>
                  <div className="set-row"><span className="set-key">Pages</span><span className="set-val">{resolved.pages.join(", ")}</span></div>
                  <div className="set-row">
                    <span className="set-key">Sections</span>
                    <span className="set-val">
                      {reg.sections.always.join(", ")}
                      {resolved.sections.length ? ` + ${resolved.sections.join(", ")}` : ""}
                    </span>
                  </div>
                  <div className="set-row">
                    <span className="set-key">Theme</span>
                    <span className="set-val">
                      {draft.theme
                        ? (resolved.direction?.theme?.label || draft.theme.name)
                        : "the style’s own palette"}
                    </span>
                  </div>
                </div>

                {mode === "compare" ? (
                  <div className="card highlight">
                    <strong>Comparing {compareList.length} styles</strong>
                    <div className="row wrap">
                      {compareList.map((s) => <span key={s.key} className="chip on">{s.label}</span>)}
                    </div>
                    <p className="muted small">
                      One full run per style above, all from this same brief - the same crew, the same checks, the
                      same approval gate. The brief itself stores no single style, so each variation is built in the
                      style named beside it.
                    </p>
                  </div>
                ) : (
                  <div className="card highlight">
                    <div className="row between wrap">
                      <strong>{resolved.style.label}</strong>
                      <span className="row">
                        {SWATCHES.map((k) => (
                          <span key={k} className="sw" style={{ background: resolved.style.palette[k] }} aria-hidden="true" />
                        ))}
                      </span>
                    </div>
                    <p className="muted small">{resolved.style.blurb}</p>
                    {resolved.direction ? (
                      <>
                        <p className="small">
                          Hero {resolved.direction.hero} · nav {resolved.direction.nav} · features {resolved.direction.features} ·
                          motif {resolved.direction.motif} · radius {resolved.direction.radius}
                        </p>
                        <p className="small">Sections after the hero: {resolved.direction.order.join(" → ")}</p>
                        {resolved.direction.color_note && (
                          <p className="small" role="status"><Icon name="alert" size={13} /> {resolved.direction.color_note}</p>
                        )}
                      </>
                    ) : (
                      <p className="small">
                        Layout: hero {resolved.style.hero}, nav {resolved.style.nav}, features {resolved.style.features},
                        motif {resolved.style.motif}. The run composes the full direction when it starts.
                      </p>
                    )}
                    <p className="muted small">{resolved.note}</p>
                  </div>
                )}
                <p className="muted small">
                  Starting now creates the project with this brief and queues the run. Nothing deploys until you approve it.
                </p>
              </div>
            )}
          </div>
        )}

        {tried && stepBad(step) && (
          <div className="error" role="alert">{STEP_KEYS[step].map((k) => errors[k]).filter(Boolean).join(" ")}</div>
        )}

        <footer className="wiz-foot">
          <div className="row">
            <button className="btn ghost" disabled={step === 0 || busy} onClick={() => go(step - 1)}>
              <Icon name="left" size={15} /> Back
            </button>
            <span className="muted small" role="status">Draft saves as you type.</span>
          </div>
          <div className="row">
            {step === 0 && <button className="btn ghost" onClick={clearDraft} disabled={busy}>Clear draft</button>}
            {step < STEPS.length - 1 ? (
              <button className="btn primary" disabled={busy} onClick={() => (stepBad(step) ? setTried(true) : go(step + 1))}>
                Next <Icon name="arrowRight" size={15} />
              </button>
            ) : (
              <button className="btn primary" disabled={busy || starting || resolving} onClick={launch}>
                {busy || starting ? "Starting the crew…"
                  : <><Icon name="rocket" size={16} /> {mode === "compare" ? `Start ${draft.compare.length} variations` : "Start the crew"}</>}
              </button>
            )}
          </div>
        </footer>
        {startErr && <div className="error" role="alert">{startErr}</div>}
      </section>
    </>
  );
}
