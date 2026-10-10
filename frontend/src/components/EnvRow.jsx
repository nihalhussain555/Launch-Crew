import Icon from "./Icon";

const SOURCE_TONE = { environment: "ok", ".env file": "", default: "warn" };

/** One variable, read straight off the Settings model the running service uses. */
export default function EnvRow({ v }) {
  const shown = v.secret
    ? (v.set ? `${v.length} chars · sha256 ${v.fingerprint}` : "not set")
    : (v.value === "" || v.value === null ? "not set" : String(v.value));
  return (
    <li className="env-row">
      <div className="env-head">
        <code className="env-name">{v.name}</code>
        {v.required && <span className="badge">required</span>}
        {v.secret && <span className="badge"><Icon name="key" size={10} /> secret</span>}
        <span className={`pill ${SOURCE_TONE[v.source] || ""}`}>{v.source}</span>
      </div>
      <p className={`env-val ${v.set ? "" : "unset"}`} title={v.secret ? "Secrets are never sent to the browser" : shown}>
        {shown}
      </p>
      {v.note && <p className="env-note">{v.note}</p>}
    </li>
  );
}
