import { useEffect, useState } from "react";
import { api } from "../api";
import { copyText } from "../utils";
import { useToast } from "../toast";
import EmptyState from "./EmptyState";
import EnvRow from "./EnvRow";
import ErrorState from "./ErrorState";
import Icon from "./Icon";
import Modal from "./Modal";

const LEVEL_ICON = { error: "close", warn: "alert", info: "help" };
const LEVEL_TONE = { error: "err", warn: "warn", info: "" };

/**
 * Environment / secrets manager. The server only ever reports presence, length and a SHA-256
 * fingerprint for secret fields, so there is nothing sensitive here to leak into the DOM.
 */
export default function EnvironmentModal({ open, onClose }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [template, setTemplate] = useState(null);
  const [show, setShow] = useState(false);

  const load = () => {
    setErr("");
    Promise.all([api.configStatus(), api.envExample()])
      .then(([d, t]) => { setData(d); setTemplate(t); })
      .catch((e) => setErr(e.message));
  };

  useEffect(() => {
    if (!open) { setData(null); setErr(""); setQ(""); setTemplate(null); setShow(false); return undefined; }
    load();
  }, [open]);

  // Copy starts inside the click handler so the browser still treats it as a user gesture.
  const copyTemplate = () => {
    if (!template) return;
    copyText(template.text).then((ok) => toast(ok ? "Template copied - fill in the keys marked REQUIRED"
      : "Clipboard blocked; open the template and copy it by hand", ok ? "success" : "info"));
  };

  const needle = q.trim().toLowerCase();
  const byField = Object.fromEntries((data?.variables || []).map((v) => [v.name, v]));
  const groups = (data?.groups || []).map((g) => ({
    ...g,
    variables: g.variables.filter((n) => !needle || n.toLowerCase().includes(needle) || (byField[n]?.note || "").toLowerCase().includes(needle)),
  })).filter((g) => g.variables.length);

  return (
    <Modal open={open} onClose={onClose} title="Service environment" size="lg"
      footer={<>
        <button className="btn ghost" onClick={onClose}>Close</button>
        <button className="btn ghost" onClick={() => setShow((s) => !s)} disabled={!template} aria-pressed={show}>
          <Icon name={show ? "eyeOff" : "eye"} size={15} /> {show ? "Hide" : "Preview"} .env template
        </button>
        <button className="btn primary" onClick={copyTemplate} disabled={!template} data-autofocus>
          <Icon name="layers" size={15} /> Copy template
        </button>
      </>}>
      {err && <ErrorState title="Couldn’t read the configuration" message={err} retry={load} />}
      {!data && !err && <div className="card skeleton" style={{ height: 160 }} />}

      {data && (
        <>
          <p className="muted small">{data.note}</p>
          <div className="row wrap env-summary">
            <span className="pill">environment: {data.app_env}</span>
            <span className="pill">{data.counts.total} variables</span>
            <span className="pill ok">{data.counts.from_environment} from env</span>
            <span className="pill">{data.counts.from_dotenv} from .env</span>
            <span className={`pill ${data.counts.using_default ? "warn" : "ok"}`}>{data.counts.using_default} still default</span>
            <span className="pill">{data.counts.secrets} secret(s)</span>
          </div>

          {!!data.missing_required.length && (
            <div className="error" role="alert">Required but empty: {data.missing_required.join(", ")}</div>
          )}

          {!!data.advice.length && (
            <ul className="checks env-advice">
              {data.advice.map((a, i) => (
                <li key={i} className={LEVEL_TONE[a.level]}>
                  <span><Icon name={LEVEL_ICON[a.level] || "help"} size={17} /></span>
                  <div>{a.message}</div>
                </li>
              ))}
            </ul>
          )}

          <label className="env-filter">
            Filter variables
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, or part of a note" aria-label="Filter variables" />
          </label>

          {!groups.length && <EmptyState icon="search" title="No variable matches" text="Clear the filter to see the whole inventory." />}

          {groups.map((g) => (
            <section key={g.group} className="env-group">
              <h3>{g.group}</h3>
              <ul className="env-list">
                {g.variables.map((name) => byField[name] && <EnvRow key={name} v={byField[name]} />)}
              </ul>
            </section>
          ))}

          {show && template && (
            <section className="stack">
              <div className="row between">
                <h3 className="env-template-title">Generated .env template</h3>
                <span className="muted small">{template.bytes} bytes · secrets included: {template.secrets_included ? "yes" : "no"}</span>
              </div>
              <pre className="file-view env-template" aria-label="Environment template text">{template.text}</pre>
            </section>
          )}
        </>
      )}
    </Modal>
  );
}
