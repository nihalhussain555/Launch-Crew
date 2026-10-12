import { useState } from "react";
import Icon from "./Icon";

/**
 * A short list of values edited as removable chips: requested features, page names.
 * `clean` normalises what was typed, `errorFor` rejects a single value, and the list is capped at `max`,
 * which mirrors the backend's SiteSpec checks so the wizard refuses what the API would refuse.
 */
export default function TagInput({ id, label, hint, values = [], onChange, max = 10,
                                   placeholder = "", clean = (v) => v, errorFor = () => "" }) {
  const [text, setText] = useState("");
  const [err, setErr] = useState("");

  const add = (ev) => {
    ev.preventDefault();
    const value = clean(text.trim());
    if (!value) return;
    if (values.length >= max) { setErr(`Up to ${max} entries - remove one to add another.`); return; }
    if (values.includes(value)) { setErr(`“${value}” is already on the list.`); return; }
    const bad = errorFor(value);
    if (bad) { setErr(bad); return; }
    onChange([...values, value]);
    setText("");
    setErr("");
  };

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <form className="tag-form" onSubmit={add}>
        <input id={id} value={text} placeholder={placeholder} maxLength={80} autoComplete="off"
          onChange={(e) => { setText(e.target.value); setErr(""); }} />
        <button className="btn small" type="submit" disabled={!text.trim()}>
          <Icon name="plus" size={14} /> Add
        </button>
      </form>
      {values.length > 0 ? (
        <ul className="tag-list" aria-label={`${label}: ${values.length} entered`}>
          {values.map((v) => (
            <li key={v}>
              <span className="chip on">{v}</span>
              <button className="icon-btn tag-drop" type="button" aria-label={`Remove ${v}`}
                onClick={() => onChange(values.filter((x) => x !== v))}>
                <Icon name="close" size={13} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <span className="muted small">Nothing yet.</span>
      )}
      {err ? <p className="field-hint" role="alert">{err}</p>
            : hint ? <p className="muted small">{hint}</p> : null}
    </div>
  );
}
