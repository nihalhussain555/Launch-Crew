/* The theme customizer's controls, drawn entirely from `GET /api/themes/registry`: the same family keys,
   preset names, colour slots and limits the server stores, so every control here is a control the API
   accepts and nothing is a second list of names for the two to drift apart from.
   Swatches show the colour the page actually gets — the resolved theme — so a value AA had to move is
   visible where it is used, and `ContrastPanel` says which ones moved and why. */
import { useEffect, useState } from "react";
import Icon from "./Icon";

const HEX = /^#[0-9a-f]{6}$/i;
const SLOT_LABEL = {
  background: "Page background", surface: "Panel surface", text: "Body text",
  primary: "Primary / buttons", secondary: "Secondary brand", accent: "Accent",
};
const DERIVED_LABEL = {
  muted_text: "Muted text", primary_text: "Button label", secondary_text: "Secondary label",
  accent_text: "Accent label", border: "Hairline", band: "Tinted band",
};
const GROUP_LABEL = {
  density: "Spacing density", width: "Container width", radius: "Corner radius",
  shadow: "Shadows", button: "Buttons", card: "Cards",
};
const GROUP_ORDER = ["density", "width", "radius", "shadow", "button", "card"];
const EFF_KEY = { radius: "radius_key", width: "width_key" };
/** The six slots a user edits; the rest of a palette is derived, so a swatch row draws exactly these. */
export const SWATCH_KEYS = ["background", "surface", "text", "primary", "secondary", "accent"];

/** One colour slot: a native picker, a hex field that only commits a full triplet, and the family's own value. */
function ColorField({ slot, value, typed, seed, disabled, onPick, onUseFamily }) {
  const [text, setText] = useState(value);
  const [focused, setFocused] = useState(false);
  useEffect(() => { if (!focused) setText(typed || value); }, [value, typed, focused]);

  const changed = seed && HEX.test(value) && value.toLowerCase() !== seed.toLowerCase();
  const invalid = text !== "" && !HEX.test(text);

  return (
    <div className="ds-color">
      <span className="ds-color-key">{SLOT_LABEL[slot] || slot}</span>
      <input type="color" value={value} disabled={disabled} aria-label={`${SLOT_LABEL[slot] || slot} colour picker`}
        onChange={(e) => { setText(e.target.value); onPick(slot, e.target.value); }} />
      <input className="mono" value={text} maxLength={7} disabled={disabled} spellCheck={false}
        placeholder="#000000" aria-label={`${SLOT_LABEL[slot] || slot} hex value`}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); if (invalid) setText(value); }}
        onChange={(e) => { const v = e.target.value; setText(v); if (HEX.test(v)) onPick(slot, v.toLowerCase()); }} />
      {invalid && <span className="pill warn" role="status">hex only</span>}
      {changed && (
        <button type="button" className="btn ghost small" disabled={disabled} onClick={onUseFamily}
          title={`The palette family uses ${seed}`}>
          <Icon name="undo" size={13} /> family
        </button>
      )}
    </div>
  );
}

/** The whole control set: palette family, mode, six colour slots, type pairing and the six preset groups. */
export default function ThemeControls({ reg, controls, resolved, onChange, disabled = false }) {
  if (!reg) return <div className="card skeleton" style={{ height: 200 }} aria-busy="true" />;

  const mode = reg.modes.includes(controls.mode) ? controls.mode : reg.default.mode;
  const family = reg.families.find((f) => f.key === controls.family) || reg.families[0];
  const seed = family.modes[mode].colors;
  const overrides = controls.colors || {};
  const colors = resolved?.colors || seed;
  const derived = resolved?.derived || {};
  const scale = Number(resolved?.scale ?? controls.scale ?? family.scale);
  const pairing = resolved?.pairing || controls.pairing || family.pairing;
  const faces = resolved?.fonts || (reg.pairings.find((p) => p.key === pairing) ?? {});
  const active = (g) => ((resolved || controls)[EFF_KEY[g] || g] || "");

  // A family or mode switch is a new starting palette: the stored colours belong to the one being left,
  // and keeping them would show a swatch that no longer describes what was picked.
  const applyFamily = (f) => onChange({
    family: f.key, mode, colors: {}, pairing: f.pairing, radius: f.radius, density: f.density,
    shadow: f.shadow, button: f.button, card: f.card, scale: f.scale, width: "",
  });
  const switchMode = (next) => onChange({ mode: next, colors: {} });
  const pick = (slot, hex) => onChange({ colors: { ...overrides, [slot]: hex } });
  const clearSlot = (slot) => {
    const next = { ...overrides };
    delete next[slot];
    onChange({ colors: next });
  };

  return (
    <div className="ds-controls stack">
      <section className="stack">
        <div className="row between wrap">
          <h3>Palette family</h3>
          <div className="seg" role="group" aria-label="Light or dark">
            {reg.modes.map((m) => (
              <button key={m} type="button" className={mode === m ? "on" : ""} aria-pressed={mode === m}
                disabled={disabled} onClick={() => switchMode(m)}>
                <Icon name={m === "dark" ? "moon" : "sun"} size={14} /> {m}
              </button>
            ))}
          </div>
        </div>
        <div className="style-grid" role="group" aria-label="Palette families">
          {reg.families.map((f) => {
            const on = f.key === family.key;
            const sw = f.modes[mode].colors;
            return (
              <button type="button" key={f.key} className={`style-card card ${on ? "on" : ""}`}
                aria-pressed={on} disabled={disabled} onClick={() => applyFamily(f)}>
                <span className="sw-row" aria-hidden="true">
                  {SWATCH_KEYS.map((k) => <span key={k} className="sw" style={{ background: sw[k] }} />)}
                </span>
                <strong className="row">
                  {f.label}
                  {on && <span className="style-flag"><Icon name="check" size={13} /> Selected</span>}
                </strong>
                <span className="muted small">{f.blurb}</span>
                <span className="row wrap">
                  <span className="pill">{f.pairing}</span>
                  <span className="pill">{f.radius} corners</span>
                  <span className="pill">{f.scale}x type</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="stack">
        <h3>Colours</h3>
        <div className="ds-colors">
          {reg.colors.map((slot) => (
            <ColorField key={slot} slot={slot} value={colors[slot]} typed={overrides[slot]} seed={seed[slot]}
              disabled={disabled} onPick={pick} onUseFamily={() => clearSlot(slot)} />
          ))}
        </div>
        {!!Object.keys(derived).length && (
          <div className="row wrap ds-derived">
            <span className="side-label">Derived</span>
            {Object.entries(derived).map(([k, v]) => (
              <span key={k} className="pill" title={`${DERIVED_LABEL[k] || k}: ${v}`}>
                <span className="sw" style={{ background: v }} aria-hidden="true" /> {DERIVED_LABEL[k] || k}
              </span>
            ))}
          </div>
        )}
        <p className="muted small">Everything except these six is calculated from them — button labels, muted
          text, hairlines and tinted bands cannot be set to something unreadable by hand. A swatch shows the
          colour the page gets after the accessibility pass.</p>
      </section>

      <section className="stack">
        <h3>Typography</h3>
        <div className="row wrap">
          {reg.pairings.map((p) => (
            <button key={p.key} type="button" className={`chip ${p.key === pairing ? "on" : ""}`}
              aria-pressed={p.key === pairing} disabled={disabled} title={p.blurb}
              onClick={() => onChange({ pairing: p.key })}>{p.label}</button>
          ))}
        </div>
        <p className="ds-type" aria-hidden="true">
          <span className="ds-type-h" style={{ fontFamily: faces.heading }}>Aa Heading</span>
          <span className="ds-type-b" style={{ fontFamily: faces.body }}>Body copy at the chosen scale</span>
        </p>
        <label className="ds-scale">
          <span>Type scale <strong className="mono">{scale.toFixed(2)}×</strong></span>
          <input type="range" min={reg.scale.min} max={reg.scale.max} step={reg.scale.step} value={scale}
            disabled={disabled} aria-label="Type scale"
            onChange={(e) => onChange({ scale: Number(e.target.value) })} />
          {Math.abs(scale - 1) >= 0.005 && (
            <button type="button" className="btn ghost small" disabled={disabled} onClick={() => onChange({ scale: 1 })}>
              <Icon name="undo" size={13} /> 1.00×
            </button>
          )}
        </label>
        <p className="muted small">System font stacks only: a generated page cannot load a web font, so a name
          here is a font the browser really has.</p>
      </section>

      <section className="stack">
        <h3>Global controls</h3>
        {GROUP_ORDER.map((g) => (
          <div key={g} className="ds-group">
            <span className="side-label">{GROUP_LABEL[g]}</span>
            <div className="row wrap">
              {reg.presets[g].map((p) => (
                <button key={p.key} type="button" className={`chip ${p.key === active(g) ? "on" : ""}`}
                  aria-pressed={p.key === active(g)} disabled={disabled} title={p.blurb}
                  onClick={() => onChange({ [g]: p.key })}>{p.label}</button>
              ))}
            </div>
          </div>
        ))}
        <p className="muted small">One token each: the page reads them from its <code className="inline-code">:root</code>{" "}
          block, so changing a corner radius here restyles every component that uses it rather than patching
          each element.</p>
      </section>
    </div>
  );
}

/** The accessibility report for the theme being edited: every pair the crew measures, with what it moved. */
export function ContrastPanel({ contrast, notes, warningsOnly = false }) {
  const rows = (contrast || []).filter((c) => (warningsOnly ? !c.passes : true));
  return (
    <div className="ds-contrast stack">
      <div className="row between wrap">
        <h3>Contrast (WCAG AA)</h3>
        <span className={`pill ${rows.every((c) => c.passes) ? "ok" : "err"}`}>
          {rows.filter((c) => c.passes).length}/{rows.length} pass
        </span>
      </div>
      <ul className="ds-contrast-list">
        {rows.map((c) => (
          <li key={c.pair} className="ds-contrast-row" title={`on ${c.background}`}>
            <span className="set-key">{c.pair}</span>
            <span className="row wrap sw-row" aria-hidden="true">
              <span className="sw" style={{ background: c.foreground }} />
              <span className="sw" style={{ background: c.background }} />
            </span>
            <span className="mono">{Number(c.ratio).toFixed(2)}:1</span>
            <span className={`pill ${c.passes ? "ok" : "err"}`}>{c.passes ? "AA" : `below ${c.minimum}`}</span>
          </li>
        ))}
        {!rows.length && <li className="muted small">All {contrast?.length || 0} measured pairs pass.</li>}
      </ul>
      {!!notes?.length && (
        <ul className="ds-notes">
          {notes.map((n) => (
            <li key={n} role="status"><Icon name="alert" size={14} /> {n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
