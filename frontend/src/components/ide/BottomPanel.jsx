import { useEffect, useState } from "react";
import { api } from "../../api";
import Icon from "../Icon";
import { timeAgo } from "../../utils";

const SEV = { 8: "err", 4: "warn", 2: "", 1: "" };       // Monaco MarkerSeverity values
const TABS = [
  { id: "problems", label: "Problems", icon: "alert" },
  { id: "output", label: "Build", icon: "cpu" },
  { id: "tests", label: "Tests", icon: "check" },
  { id: "terminal", label: "Terminal", icon: "monitor" },
  { id: "logs", label: "Run log", icon: "book" },
];

function Row({ kind, file, line, text, onJump }) {
  return (
    <button className={`ide-prob ${kind}`} onClick={() => file && onJump({ file, line: line || 1, column: 1 })}>
      <span className="ide-prob-mark">{kind === "err" ? "×" : kind === "warn" ? "!" : "·"}</span>
      <span className="ide-prob-where mono">{file ? `${file}${line ? `:${line}` : ""}` : "workspace"}</span>
      <span className="ide-prob-text">{text}</span>
    </button>
  );
}

/**
 * The IDE's lower panel, and everything in it is read from a real endpoint:
 * editor diagnostics, the last validation the checks produced, the suite this build generated,
 * the run's own SSE log, and the execution capability verdict - which on this deployment says that
 * running project code needs a sandbox, and is never given a simulated line of output.
 */
export default function BottomPanel({ runId, overview, run, markers, events, connected, onJump, busy, setBusy }) {
  const [tab, setTab] = useState("problems");
  const [tests, setTests] = useState(null);
  const [exec, setExec] = useState(null);
  const [execErr, setExecErr] = useState("");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");

  const version = run?.state?.html_version ?? overview?.version ?? 0;
  useEffect(() => {
    setTests(null);
    if (tab !== "tests") return;
    api.tests(runId).then(setTests).catch((e) => setTests({ error: e.message }));
  }, [tab, runId, version]);                                    // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (tab !== "terminal" || exec) return;
    api.ideExec(runId).then(setExec).catch((e) => setExecErr(e.message));
  }, [tab, runId, exec]);

  const problems = [
    ...Object.entries(markers || {}).flatMap(([file, list]) => (list || []).map((m) => ({
      kind: SEV[m.severity] || "info", file, line: m.startLineNumber, text: m.message,
    }))),
    ...(run?.state?.sanitizer_violations || []).map((v) => ({ kind: "warn", file: "index.html", line: 0, text: `Sanitizer: ${v}` })),
    ...(overview?.validation?.status && overview.validation.status !== "clean"
      ? [{ kind: "err", file: "", line: 0, text: `Last change ${overview.validation.status}: ${overview.validation.check_errors} check error(s), ${overview.validation.check_warnings} warning(s) on page v${overview.validation.version}` }]
      : []),
    ...(run?.state?.check_results || []).filter((c) => !c.passed).map((c) => ({
      kind: c.severity === "error" ? "err" : "warn", file: "index.html", line: 0,
      text: `${c.label} (${c.viewport || "page"}): ${c.detail || "failed"}`,
    })),
  ];

  const askRun = async (e) => {
    e.preventDefault();
    setBusy("exec"); setExecErr("");
    try {
      await api.ideRun(runId, { file: command, args });
      setExecErr("The backend accepted a run request, which it should not have on this deployment.");
    } catch (ex) { setExecErr(ex.message); } finally { setBusy(""); }
  };

  return (
    <section className="ide-bottom" aria-label="IDE output panel">
      <div className="ide-bottom-head" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`ide-bottom-tab ${tab === t.id ? "on" : ""}`}
            onClick={() => setTab(t.id)}>
            <Icon name={t.icon} size={14} /> {t.label}
            {t.id === "problems" && !!problems.filter((p) => p.kind === "err").length && (
              <span className="pill err">{problems.filter((p) => p.kind === "err").length}</span>)}
            {t.id === "tests" && tests?.ran && (
              <span className={`pill ${tests.failed ? "err" : "ok"}`}>{tests.failed ? `${tests.failed} failing` : "passing"}</span>)}
          </button>
        ))}
        <span className="muted small ide-bottom-state">{connected ? "streaming" : "stream closed"}</span>
      </div>

      <div className="ide-bottom-body">
        {tab === "problems" && (problems.length ? problems.map((p, i) => (
          <Row key={i} {...p} onJump={onJump} />
        )) : <p className="muted small">No diagnostics: the open files report no parser or language errors and the
          last Chromium pass was clean.</p>)}

        {tab === "output" && (
          <div className="stack">
            <p className="muted small">page v{version} · {overview?.files?.length || 0} file(s) ·
              {" "}{overview?.revisions ?? 0} revision(s) spent · {overview?.snapshots?.length || 0} snapshot(s) kept of{" "}
              {overview?.limits?.keep_snapshots}</p>
            {(run?.state?.versions || []).slice(-6).reverse().map((v) => (
              <div key={v.v} className="ide-out-row">
                <span className={`pill ${v.errors ? "err" : "ok"}`}>v{v.v}</span>
                <span className="muted small">{timeAgo(v.at)}</span>
                <span className="ide-out-note">{v.note || "published build"}</span>
                <span className="muted small">{Math.max(1, Math.round((v.bytes || 0) / 1024))} KB</span>
                {v.readiness != null && <span className="pill">{v.readiness}/100</span>}
                {!!v.errors?.length && <span className="pill err">{v.errors.length} error(s)</span>}
              </div>
            ))}
            {overview?.changed_files && (
              <p className="muted small">Last change moved {overview.changed_files.lines_added} added /{" "}
                {overview.changed_files.lines_removed} removed across{" "}
                {(overview.changed_files.files || []).length} file(s).</p>
            )}
            <p className="muted small">There is no separate compile step: the page is assembled by the Engineer,
              sanitized, published as this file set and then measured in Chromium. A save of
              <code className="inline-code"> index.html</code> is that build.</p>
          </div>
        )}

        {tab === "tests" && (!tests ? <div className="card skeleton" style={{ height: 60 }} /> : tests.error ? (
          <p className="muted small">{tests.error}</p>
        ) : (
          <div className="stack">
            <div className="row wrap">
              <span className={`pill ${tests.ran ? (tests.failed ? "err" : "ok") : "warn"}`}>
                {!tests.ran ? "did not run" : tests.failed ? `${tests.failed} failing` : "all passing"}</span>
              <span className="pill">{(tests.cases || []).length} case(s)</span>
              <span className="pill">page v{tests.version}</span>
              {tests.reason && <span className="muted small">{tests.reason}</span>}
            </div>
            {(tests.cases || []).map((c, i) => (
              <div key={i} className={`ide-out-row ${c.ok ? "" : "is-bad"}`}>
                <span className={`pill ${c.ok ? "ok" : "err"}`}>{c.ok ? "pass" : "fail"}</span>
                <span className="ide-out-note">{c.name}</span>
                {!c.ok && <span className="muted small">{c.detail}</span>}
              </div>
            ))}
            {tests.output && (
              <details><summary className="muted small">Interpreter output</summary>
                <pre className="ide-out-pre">{tests.output}</pre></details>
            )}
          </div>
        ))}

        {tab === "terminal" && (
          <div className="stack">
            {execErr && !exec ? <p className="ide-form-problem" role="alert">{execErr}</p> : null}
            {exec && (
              <>
                <div className="row wrap">
                  <span className={`pill ${exec.available ? "ok" : "warn"}`}>{exec.available ? "runner available" : "no sandbox"}</span>
                  <span className="pill">{exec.runtime_found ? `${exec.runtime} installed` : `${exec.runtime || "no runtime"} not installed`}</span>
                </div>
                <p className="ide-out-note">{exec.reason}</p>
                <p className="muted small">This panel prints only what a real process wrote. Nothing here is a
                  simulated shell: the backend refuses to execute workspace code outside an isolated runner, and
                  this deployment has none.</p>
                {!!exec.missing?.length && (
                  <ul className="ide-missing">
                    {exec.missing.map((m, i) => <li key={i}>{m}</li>)}
                  </ul>
                )}
                {!!exec.configuration && (
                  <details><summary className="muted small">What a deployment would set</summary>
                    <p className="muted small mono">SANDBOX_RUNTIME={exec.configuration.SANDBOX_RUNTIME || "(empty)"}</p>
                    <p className="muted small">{exec.configuration.note}</p>
                  </details>
                )}
                {!!exec.safe_alternatives?.length && (
                  <ul className="ide-missing">
                    {exec.safe_alternatives.map((a, i) => <li key={i}>{a}</li>)}
                  </ul>
                )}
              </>
            )}
            <form className="ide-runform" onSubmit={askRun}>
              <select value={command} onChange={(e) => setCommand(e.target.value)} aria-label="File to run">
                <option value="">choose a file</option>
                {(overview?.files || []).map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
              </select>
              <input value={args} onChange={(e) => setArgs(e.target.value)} maxLength={200}
                placeholder="arguments" aria-label="Arguments for the file" />
              <button className="btn primary small" type="submit" disabled={busy === "exec" || !command}>
                <Icon name="hash" size={14} /> Ask the backend
              </button>
            </form>
            {execErr && exec ? <p className="ide-form-problem" role="alert">{execErr}</p> : null}
          </div>
        )}

        {tab === "logs" && (
          <div className="ide-log">
            {!events.length && <p className="muted small">Nothing on this run's event feed yet.</p>}
            {events.slice().reverse().map((e) => (
              <div key={e.seq} className="ide-log-row">
                <span className="muted small mono">{String(e.seq).padStart(3, "0")}</span>
                <span className={`pill ${e.type === "failed" ? "err" : ""}`}>{e.type.replace(/_/g, " ")}</span>
                <span className="ide-out-note mono">{JSON.stringify(e.data).slice(0, 240)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
