import Icon from "./Icon";

const SLOTS = ["hero", "nav", "features", "motif"];
const SWATCHES = ["background", "surface", "primary", "accent", "text"];

/**
 * The design registry as selectable cards. Each card shows what actually differs between styles - the
 * hero, navigation, feature layout and motif it drives, the corner radius and the palette - so a choice
 * is made on the composition, not on a thumbnail. `mode="compare"` multi-selects up to `max` styles.
 */
export default function StylePicker({ styles, mode = "single", value = "", values = [], notes = {},
                                      onChange, max = 4 }) {
  const compare = mode === "compare";
  const picked = compare ? values : [value];

  const toggle = (key) => {
    if (!compare) return onChange(key === value ? "" : key);
    if (values.includes(key)) return onChange(values.filter((k) => k !== key));
    if (values.length < max) onChange([...values, key]);
  };

  return (
    <div className="style-grid" role="group" aria-label="Design styles">
      {styles.map((s) => {
        const on = picked.includes(s.key);
        return (
          <button type="button" key={s.key} className={`style-card card ${on ? "on" : ""}`}
            aria-pressed={on} onClick={() => toggle(s.key)}>
            <span className="sw-row" aria-hidden="true">
              {SWATCHES.map((k) => <span key={k} className="sw" style={{ background: s.palette[k] }} />)}
            </span>
            <strong className="row">
              {s.label}
              {on && <span className="style-flag"><Icon name="check" size={13} />
                {compare ? `Variation ${values.indexOf(s.key) + 1}` : "Selected"}</span>}
            </strong>
            <span className="muted small">{s.blurb}</span>
            <span className="row wrap">
              {SLOTS.map((k) => (
                <span key={k} className="pill" title={notes[`${k}_notes`]?.[s[k]] || ""}>{k}: {s[k]}</span>
              ))}
            </span>
            <span className="small muted">Corners {s.radius} · primary {s.palette.primary}</span>
            {(s.default_sections || []).length > 0 && (
              <span className="style-secs">
                <span className="side-label">Adds sections</span>
                <span className="row wrap">{s.default_sections.map((x) => <span key={x} className="chip">{x}</span>)}</span>
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
