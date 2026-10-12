/* The design system: edit appearance once, see it drawn everywhere.

   Two honest halves. The preview is the crew's own deterministic renderer
   (`POST /api/themes/preview-page` → the same `build_page` an offline run publishes), so the swatches drive
   a real `:root` block rather than a React imitation of one — and the copy in it is the sample copy, marked
   as such, because a preview of *appearance* has no business inventing testimonials or prices. The library is
   the user's own saved themes: controls only, re-resolved on every read, so a future accessibility fix or new
   preset reaches a theme saved before it existed.
*/
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ConfirmModal from "../components/ConfirmModal";
import ThemeControls, { ContrastPanel, SWATCH_KEYS } from "../components/ThemeControls";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import { useThemeRegistry } from "../hooks/useThemeRegistry";
import { useToast } from "../toast";
import { timeAgo } from "../utils";

const VIEWPORTS = [
  { id: "desktop", label: "Desktop", note: "1280 wide" },
  { id: "tablet", label: "Tablet", note: "768 wide" },
  { id: "mobile", label: "Mobile", note: "375 wide, like the audit" },
];
// The keys `app/agents/theme.py` puts in a theme's token map, in reading order. A key the theme does not
// set is absent from the response, so this only sorts what really arrived — nothing is invented here.
const TOKEN_ORDER = ["space", "radius", "art_radius", "card_radius", "card_pad", "card_bg", "card_border",
                     "card_shadow", "card_blur", "btn_bg", "btn_fg", "btn_border", "btn_radius", "btn_shadow",
                     "shadow", "shadow_strong", "border", "band", "focus_ring", "secondary", "secondary_text",
                     "width"];

/** One library card: what the theme is called, what it draws, and the actions that work on the saved copy. */
function ThemeCard({ t, current, busy, onEdit, onDuplicate, onDelete }) {
  return (
    <li className={`ws-item ${current ? "current" : ""}`}>
      <div className="ws-main">
        <div className="row wrap between">
          <div className="row wrap">
            <strong>{t.name || t.label}</strong>
            <span className="pill">{t.mode}</span>
            <span className="pill">{t.family}</span>
            {t.has_previous && <span className="pill warn">previous kept</span>}
            {current && <span className="pill ok">open</span>}
          </div>
          <span className="muted small">{timeAgo(t.updated_at)}</span>
        </div>
        <div className="sw-row" aria-hidden="true">
          {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: t.palette[k] }} />)}
        </div>
        <p className="muted small">{t.summary}</p>
        <div className="row wrap">
          <span className={`pill ${t.contrast.every((c) => c.passes) ? "ok" : "err"}`}>
            {t.contrast.filter((c) => c.passes).length}/{t.contrast.length} AA
          </span>
          {t.notes.slice(0, 2).map((n) => <span key={n} className="pill warn" title={n}>{n}</span>)}
        </div>
      </div>
      <div className="row wrap">
        <button className="btn small" onClick={onEdit} disabled={!!busy}><Icon name="sliders" size={14} /> Edit</button>
        <button className="btn ghost small" onClick={() => onDuplicate(t.id)} disabled={!!busy}
          title="A copy to experiment on; the original is untouched">
          <Icon name="plus" size={14} /> Duplicate
        </button>
        <Link className="btn ghost small" to={`/new?theme=${t.id}`}>
          <Icon name="rocket" size={14} /> Use in a new project
        </Link>
        <button className="btn ghost small" onClick={onDelete} disabled={!!busy}
          title="Forget this saved theme. Projects built with it keep their own copy of the controls.">
          <Icon name="close" size={14} /> Delete
        </button>
      </div>
    </li>
  );
}

export default function DesignSystem() {
  const toast = useToast();
  const { reg, error: regErr, reload } = useThemeRegistry();
  const [styles, setStyles] = useState(null);
  const [controls, setControls] = useState(null);
  const [name, setName] = useState("");
  const [styleKey, setStyleKey] = useState("");
  const [mode, setMode] = useState("desktop");
  const [preview, setPreview] = useState(null);
  const [previewErr, setPreviewErr] = useState("");
  const [redrawing, setRedrawing] = useState(false);
  const [library, setLibrary] = useState(null);
  const [libErr, setLibErr] = useState("");
  const [editing, setEditing] = useState(null);   // { id } while the editor holds a saved theme
  const [busy, setBusy] = useState("");
  const [confirmDel, setConfirmDel] = useState(null);

  useEffect(() => {
    api.styles().then((d) => setStyles(d.styles || [])).catch(() => setStyles([]));
  }, []);

  useEffect(() => {
    if (reg && !controls) setControls({ ...reg.default });
  }, [reg, controls]);

  const loadLibrary = useCallback(() => {
    setLibErr("");
    api.listThemes().then(setLibrary).catch((e) => setLibErr(e.message));
  }, []);
  useEffect(loadLibrary, [loadLibrary]);

  // Live preview, debounced: a drag on a slider or a hex field is one request, not forty.
  useEffect(() => {
    if (!controls) return undefined;
    let live = true;
    setRedrawing(true);
    const t = setTimeout(() => {
      api.themePreviewPage(controls, styleKey)
        .then((d) => { if (live) { setPreview(d); setPreviewErr(""); } })
        .catch((e) => { if (live) setPreviewErr(e.message); })
        .finally(() => { if (live) setRedrawing(false); });
    }, 400);
    return () => { live = false; clearTimeout(t); };
  }, [controls, styleKey]);

  const set = useCallback((patch) => setControls((c) => ({ ...c, ...patch })), []);
  const tokens = useMemo(() => {
    const map = preview?.tokens || {};
    const keys = [...TOKEN_ORDER.filter((k) => map[k] !== undefined), ...Object.keys(map).filter((k) => !TOKEN_ORDER.includes(k))];
    return keys.map((k) => [k, map[k]]);
  }, [preview]);

  const startNew = () => {
    if (!reg) return;
    setControls({ ...reg.default });
    setName("");
    setEditing(null);
  };

  const openTheme = (t) => {
    setControls({ ...t.controls });
    setName(t.name);
    setEditing({ id: t.id });
    toast(`Editing “${t.name}”`, "info");
  };

  const save = async () => {
    setBusy("save");
    try {
      const d = editing ? await api.updateTheme(editing.id, { name, theme: controls })
                        : await api.saveTheme(name, controls);
      setControls({ ...d.controls });
      setName(d.name);
      setEditing({ id: d.id });
      toast(editing ? `“${d.name}” saved` : `“${d.name}” added to your themes`, "success");
      loadLibrary();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  // Both of these rewrite the saved copy, so the editor follows the server's answer instead of guessing.
  const runAction = async (kind, id) => {
    setBusy(kind);
    try {
      const call = { duplicate: api.duplicateTheme, reset: api.resetTheme, restore: api.restoreTheme }[kind];
      const d = await call(id);
      if (kind === "duplicate") toast(`Duplicated as “${d.name}” — the original is untouched`, "success");
      else {
        setControls({ ...d.controls });
        setName(d.name);
        setEditing({ id: d.id });
        toast(kind === "reset" ? `“${d.name}” reset to its ${d.family} palette` : `Previous version of “${d.name}” restored`, "success");
      }
      loadLibrary();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(""); }
  };

  const remove = async () => {
    try {
      await api.deleteTheme(confirmDel.id);
      if (editing?.id === confirmDel.id) startNew();
      toast(`Deleted “${confirmDel.name}”. Projects built with it keep their own copy of those controls.`, "info");
      loadLibrary();
    } catch (e) { toast(e.message, "error"); } finally { setConfirmDel(null); }
  };

  if (regErr) {
    return (
      <>
        <div className="page-head"><div><h1>Design System</h1><p className="muted">The theme registry could not be loaded.</p></div></div>
        <ErrorState title="Couldn’t load the design registry" message={regErr} retry={reload} back="/dashboard" />
      </>
    );
  }

  const saved = library?.themes || [];
  const limit = library?.limits?.per_user || reg?.limits?.themes_per_user;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Design System</h1>
          <p className="muted">One place to set colour, type, spacing, corners, shadows and density for the
            pages the crew generates. Changes are design tokens, so a component that reads them updates with
            them — nothing here patches elements one by one.</p>
        </div>
        <div className="row wrap">
          <button className="btn ghost" onClick={startNew} disabled={!reg}>
            <Icon name="plus" size={15} /> New theme
          </button>
          <Link className="btn ghost" to="/workspace"><Icon name="code" size={15} /> Re-theme a project</Link>
          <Link className="btn primary" to="/new"><Icon name="rocket" size={15} /> New project brief</Link>
        </div>
      </div>

      {!reg || !controls ? <div className="card skeleton" style={{ height: 320 }} aria-busy="true" /> : (
        <div className="ds-grid">
          <section className="card stack" aria-label="Theme controls">
            <div className="row between wrap">
              <h2>{editing ? "Editing a saved theme" : "Theme editor"}</h2>
              <span className={`pill ${editing ? "" : "warn"}`}>
                {editing ? `saved · id ${editing.id.slice(-6)}` : "not saved yet"}
              </span>
            </div>
            <label className="ds-name">
              <span>Theme name</span>
              <input value={name} maxLength={reg.limits.name} placeholder={reg.families[0].label}
                onChange={(e) => setName(e.target.value)} aria-label="Theme name" />
            </label>
            <ThemeControls reg={reg} controls={controls} resolved={preview?.theme} onChange={set} />
            <div className="row wrap ds-actions">
              <button className="btn primary" onClick={save} disabled={!!busy}>
                <Icon name="check" size={15} /> {busy === "save" ? "Saving…" : editing ? "Save changes" : "Save this theme"}
              </button>
              <button className="btn ghost" onClick={() => runAction("duplicate", editing?.id)}
                disabled={!!busy || !editing} title={editing ? "A copy to experiment on" : "Save it first, then duplicate"}>
                <Icon name="plus" size={15} /> {busy === "duplicate" ? "…" : "Duplicate"}
              </button>
              <button className="btn ghost" onClick={() => runAction("reset", editing?.id)}
                disabled={!!busy || !editing} title="Back to this family's own colours, pairing and presets. The name is kept.">
                <Icon name="refresh" size={15} /> {busy === "reset" ? "…" : "Reset to family"}
              </button>
              <button className="btn ghost" onClick={() => runAction("restore", editing?.id)}
                disabled={!!busy || !editing} title="Put back the controls this theme had before its last save or reset.">
                <Icon name="undo" size={15} /> {busy === "restore" ? "…" : "Restore previous"}
              </button>
              <button className="btn danger" onClick={() => editing && setConfirmDel({ id: editing.id, name })}
                disabled={!!busy || !editing}>
                <Icon name="close" size={15} /> Delete
              </button>
            </div>
            <p className="muted small">Saved themes are reusable settings: nothing here writes to a project or a
              running build. Applying one to a live page happens in the Code Workspace, where it is reviewed as
              a token patch and can be restored from the snapshot taken before it.</p>
          </section>

          <section className="card stack ds-preview" aria-label="Live preview">
            <div className="row between wrap">
              <h2>Live preview</h2>
              <div className="row wrap">
                <label className="ds-style-pick">
                  <span className="muted small">Layout</span>
                  <select value={styleKey} onChange={(e) => setStyleKey(e.target.value)} aria-label="Design style of the sample page"
                    disabled={!styles}>
                    <option value="">the crew’s choice</option>
                    {(styles || []).map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                  </select>
                </label>
                <div className="seg" role="group" aria-label="Viewport">
                  {VIEWPORTS.map((v) => (
                    <button key={v.id} className={mode === v.id ? "on" : ""} title={v.note} onClick={() => setMode(v.id)}>
                      {v.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="row wrap">
              <span className={`pill ${redrawing ? "warn" : ""}`}>
                {redrawing ? "redrawing…" : preview ? "drawn from these tokens" : "not drawn yet"}
              </span>
              {preview && <span className="pill">{preview.style_label}</span>}
              {preview && <span className="pill warn" title="The words are placeholders; only the appearance is real">sample copy</span>}
              <span className="pill">{name || preview?.theme?.label}</span>
            </div>
            {preview && <p className="muted small ds-summary">{preview.summary}</p>}
            {previewErr && <div className="error" role="alert">{previewErr}</div>}
            {!preview && !previewErr && reg && (
              <div className="card skeleton" style={{ height: 420 }} aria-busy="true" />
            )}

            {preview && (
              <>
                <div className="frame-wrap">
                  <iframe title="Theme preview" sandbox="allow-scripts" srcDoc={preview.html}
                    className={`frame ${mode}`} />
                </div>
                <ContrastPanel contrast={preview.contrast} notes={preview.notes} />
                <details className="ds-tokens">
                  <summary className="muted small">The {tokens.length} design tokens this theme resolves</summary>
                  <ul className="ds-token-list">
                    {tokens.map(([k, v]) => (
                      <li key={k}><span className="mono">{k}</span><span className="mono">{String(v)}</span></li>
                    ))}
                  </ul>
                  <p className="muted small">These are the values the page's <code className="inline-code">:root</code>{" "}
                    block is written from; the component CSS above only reads them.</p>
                  <p className="muted small mono">{preview.brief}</p>
                </details>
              </>
            )}
          </section>
        </div>
      )}

      <section className="card stack" aria-label="Saved themes">
        <div className="row between wrap">
          <h2>Your themes</h2>
          <span className="muted small">{library ? `${saved.length} of ${limit} saved` : "loading…"}</span>
        </div>
        {libErr && <ErrorState title="Couldn’t read your themes" message={libErr} retry={loadLibrary} />}
        {library && !saved.length && (
          <EmptyState icon="palette" title="No saved themes yet"
            text="Set the controls above and save them — a saved theme can then start any new project brief, or be applied to a live page from the Code Workspace." />
        )}
        <ul className="ws-list ds-lib">
          {saved.map((t) => (
            <ThemeCard key={t.id} t={t} busy={busy} current={editing?.id === t.id}
              onEdit={() => openTheme(t)} onDuplicate={(id) => runAction("duplicate", id)}
              onDelete={() => setConfirmDel({ id: t.id, name: t.name })} />
          ))}
        </ul>
        {!!saved.length && <p className="muted small">Opening a theme loads its stored controls only; colours,
          tokens and contrast are recomputed from them on every read, so an accessibility fix applies to themes
          you saved before it.</p>}
      </section>

      <ConfirmModal open={!!confirmDel} onClose={() => setConfirmDel(null)} onConfirm={remove} danger
        confirmLabel="Delete theme" title="Delete this theme?"
        message={`“${confirmDel?.name || "Untitled theme"}” will be removed from your library. Projects and runs
          already themed with it keep the controls stored in their own brief, so nothing generated changes.`} />
    </>
  );
}
