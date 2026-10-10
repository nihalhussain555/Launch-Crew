import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import EnvRow from "../components/EnvRow";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import Tabs from "../components/Tabs";
import { useToast } from "../toast";
import { copyText } from "../utils";

const LEVEL_ICON = { error: "close", warn: "alert", info: "help" };
const LEVEL_TONE = { error: "err", warn: "warn", info: "" };

/** The services the crew talks to, read off the same variables the backend uses. */
const CONNECTORS = [
  { key: "groq", name: "Groq", icon: "cpu", group: "LLM (Groq)",
    needs: ["GROQ_API_KEY", "GROQ_MODEL"], optional: ["GROQ_FAST_MODEL", "GROQ_VISION_MODEL"],
    used_by: "Every writing agent: Researcher, Strategist, Copywriter, Designer, Engineer, Critic and Panel.",
    off: "With MOCK_LLM=true the crew still runs: quoted-text swaps, tone words, palette and spacing asks are "
       + "applied mechanically, while free-text rewrites need a real key." },
  { key: "tavily", name: "Tavily", icon: "search", group: "Tools",
    needs: ["TAVILY_API_KEY"], optional: [],
    used_by: "The Researcher's live web lookups during the first stage of a run.",
    off: "Without a key the Researcher falls back to its built-in market heuristics, so a run still completes "
       + "with no live results." },
  { key: "netlify", name: "Netlify", icon: "rocket", group: "Tools",
    needs: ["NETLIFY_AUTH_TOKEN"], optional: [],
    used_by: "The Launcher, only after you approve a run for deploy.",
    off: "Without a token approval records a simulated deploy (deploy_mock=true) - the run, its files and its "
       + "version history are all real; only the upload is skipped." },
  { key: "mongo", name: "MongoDB", icon: "layers", group: "Database",
    needs: ["MONGO_URI", "MONGO_DB"], optional: ["STORAGE_BACKEND"],
    used_by: "Accounts, projects, runs and every published artefact.",
    off: "A mock:// URI keeps data only in memory, so runs and accounts disappear on restart." },
];

/** What this service is wired to, and the exact variables behind each connection. */
export default function Integrations() {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [template, setTemplate] = useState(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [tab, setTab] = useState("connections");
  const [show, setShow] = useState(false);

  const load = () => {
    setErr("");
    Promise.all([api.configStatus(), api.envExample()])
      .then(([d, t]) => { setData(d); setTemplate(t); })
      .catch((e) => setErr(e.message));
  };
  useEffect(load, []);

  const copyTemplate = async () => {
    if (!template) return;
    const ok = await copyText(template.text);
    toast(ok ? "Template copied - fill in the keys marked REQUIRED"
             : "Clipboard blocked; open the template and copy it by hand", ok ? "success" : "info");
  };

  const byField = Object.fromEntries((data?.variables || []).map((v) => [v.name, v]));
  const needle = q.trim().toLowerCase();
  const groups = (data?.groups || []).map((g) => ({
    ...g,
    variables: g.variables.filter((n) => !needle
      || n.toLowerCase().includes(needle) || (byField[n]?.note || "").toLowerCase().includes(needle)),
  })).filter((g) => g.variables.length);

  const tabs = [
    { id: "connections", label: "Connections", badge: CONNECTORS.length },
    { id: "inventory", label: "Variables", badge: data?.counts?.total || null },
    { id: "advice", label: "Advice", badge: data?.advice?.length || null, tone: "warn" },
    { id: "template", label: ".env template" },
  ];

  return (
    <>
      <div className="page-head">
        <div><h1>Integrations</h1><p className="muted">Every external service this deployment uses, the variables that
          configure it, and what the crew does when a key is absent.</p></div>
        <Link to="/settings" className="btn ghost small"><Icon name="gear" size={15} /> Settings</Link>
      </div>

      {err && <ErrorState title="Couldn’t read the configuration" message={err} retry={load} />}
      {!data && !err && <div className="card skeleton" style={{ height: 180 }} />}

      {data && (
        <>
          <div className="row wrap">
            <span className="pill">environment: {data.app_env}</span>
            <span className="pill">{data.counts.total} variables</span>
            <span className="pill ok">{data.counts.from_environment} from env</span>
            <span className="pill">{data.counts.from_dotenv} from .env</span>
            <span className={`pill ${data.counts.using_default ? "warn" : "ok"}`}>{data.counts.using_default} still default</span>
            <span className="pill">{data.counts.secrets} secret(s)</span>
          </div>
          <p className="muted small">{data.note}</p>

          {!!data.missing_required.length && (
            <div className="error" role="alert">Required but empty: {data.missing_required.join(", ")}</div>
          )}

          <Tabs tabs={tabs} active={tab} onChange={setTab} />

          {tab === "connections" && (
            <div className="grid-cards">
              {CONNECTORS.map((c) => {
                const missing = c.needs.filter((n) => !byField[n]?.set);
                const secrets = c.needs.filter((n) => byField[n]?.secret);
                return (
                  <section key={c.key} className="card conn-card">
                    <div className="row wrap between">
                      <div className="row wrap">
                        <span className="stat-icon"><Icon name={c.icon} size={19} /></span>
                        <strong>{c.name}</strong>
                      </div>
                      <span className={`pill ${missing.length ? "warn" : "ok"}`}>{missing.length ? "not configured" : "configured"}</span>
                    </div>
                    <p className="muted small">{c.used_by}</p>
                    <div className="row wrap">
                      {c.needs.map((n) => (
                        <span key={n} className={`pill ${byField[n]?.set ? "ok" : ""}`}>
                          {n}{byField[n]?.secret && byField[n]?.set ? ` · ${byField[n].length} chars` : ""}
                        </span>
                      ))}
                      {c.optional.filter((n) => byField[n]?.set).map((n) => <span key={n} className="pill">{n}</span>)}
                    </div>
                    {!!missing.length && <p className="muted small">{c.off}</p>}
                    <p className="muted small mono">{c.group}{secrets.length ? ` · ${secrets.length} secret key(s)` : ""}</p>
                  </section>
                );
              })}
            </div>
          )}

          {tab === "inventory" && (
            <>
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
            </>
          )}

          {tab === "advice" && (data.advice.length ? (
            <ul className="checks">
              {data.advice.map((a, i) => (
                <li key={i} className={LEVEL_TONE[a.level]}>
                  <span><Icon name={LEVEL_ICON[a.level] || "help"} size={17} /></span>
                  <div>{a.message}</div>
                </li>
              ))}
            </ul>
          ) : <EmptyState icon="check" title="Nothing to flag" text="The service reports no configuration concerns right now." />)}

          {tab === "template" && (!template ? <div className="card skeleton" style={{ height: 200 }} /> : (
            <section className="card stack">
              <div className="row wrap between">
                <h2>Generated .env template</h2>
                <div className="row wrap">
                  <span className="pill">{template.bytes} bytes</span>
                  <span className="pill ok">secrets included: {template.secrets_included ? "yes" : "no"}</span>
                  <button className="btn ghost small" onClick={() => setShow((v) => !v)} aria-pressed={show}>
                    <Icon name={show ? "eyeOff" : "eye"} size={14} /> {show ? "Hide" : "Show"}
                  </button>
                  <button className="btn primary small" onClick={copyTemplate}><Icon name="layers" size={14} /> Copy</button>
                </div>
              </div>
              <p className="muted small">Built from the settings this service reads, so it cannot drift from the code.
                Secret keys appear as a placeholder shape, never a live value.</p>
              {show && <pre className="file-view env-template" aria-label="Environment template text">{template.text}</pre>}
            </section>
          ))}
        </>
      )}
    </>
  );
}
