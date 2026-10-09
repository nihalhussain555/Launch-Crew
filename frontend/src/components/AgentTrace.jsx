import Icon from "./Icon";

/* Agent roles + event kinds map onto the custom Icon set (no emoji). */
const ROLE = { researcher: "search", strategist: "target", copywriter: "book", designer: "layers", engineer: "cpu",
  critic: "shield", panel: "user", launcher: "rocket", security: "lock", seo: "globe", accessibility: "eye",
  performance: "chart", dependency: "workflow", tester: "check" };
const AUDIT_ICON = { security: "lock", seo: "globe", accessibility: "eye", performance: "chart",
  dependency: "workflow", tests: "check" };
const NAME = { seo: "SEO" };
const cap = (s = "") => NAME[s] || s.charAt(0).toUpperCase() + s.slice(1);

function describe(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "agent_started": return { icon: ROLE[d.agent] || "sparkle", title: `${cap(d.agent)} started`, tone: "run" };
    case "agent_message":
      if (d.agent === "you") return { icon: "user", title: "You requested a change", body: d.message, tone: "run" };
      if (d.agent === "system") return { icon: "alert", title: "System notice", body: d.message, tone: "warn" };
      return { icon: "check", title: `${cap(d.agent)} finished`, body: d.message, meta: d.tokens ? `${d.tokens} tokens` : "", tone: "ok" };
    case "tool_call": return { icon: "workflow", title: `${cap(d.agent)} used ${d.tool}`, body: d.args?.query || d.url, tone: "tool" };
    case "rate_limited": return { icon: "refresh", title: "Rate limited — retrying", body: d.message, tone: "warn" };
    case "check_results": return { icon: "shield", title: `Browser checks (review ${d.iteration})`,
      body: `${d.summary.errors} error(s), ${d.summary.warnings} warning(s) of ${d.summary.total} checks`, tone: d.summary.errors ? "warn" : "ok" };
    case "critic_feedback": return { icon: "book", title: "Critic feedback", body: d.summary, tone: "warn" };
    case "audit_report": return { icon: AUDIT_ICON[d.audit.kind] || "audit", title: `${d.audit.label} · v${d.audit.version}`,
      body: `${d.audit.headline} Score ${d.audit.score}/100.`, tone: d.audit.errors ? "err" : d.audit.warnings ? "warn" : "ok" };
    case "screenshot_ready": return { icon: "eye", title: `Screenshot ready (${d.viewport})`, tone: "tool" };
    case "awaiting_approval": return { icon: "lock", title: "Waiting for your approval", body: d.message, tone: "warn" };
    case "deployed": return { icon: "rocket", title: "Deployed", body: d.url, tone: "ok" };
    case "failed": return { icon: "close", title: "Run failed", body: d.error, tone: "err" };
    default: return { icon: "sparkle", title: ev.type, tone: "" };
  }
}

export default function AgentTrace({ events, connected, status }) {
  const active = ["queued", "running", "deploying"].includes(status);
  return (
    <section className="card">
      <div className="row between">
        <h2>Agent trace</h2>
        <span className={`pill ${connected ? "ok" : active ? "warn" : ""}`}>
          <span className={`dot ${connected ? "on" : active ? "warn" : ""}`} aria-hidden="true" />
          {connected ? "Live" : active ? "Reconnecting…" : "Idle"}
        </span>
      </div>
      {events.length === 0 && <div className="muted">{active ? "Waiting for the first agent…" : "No events."}</div>}
      <ol className="timeline">
        {events.filter((e) => e.type !== "screenshot_ready").map((ev) => {
          const x = describe(ev);
          return (
            <li key={ev.seq} className={x.tone}>
              <span className="ico"><Icon name={x.icon} size={18} /></span>
              <div><strong>{x.title}</strong> {x.meta && <span className="muted small">· {x.meta}</span>}
                {x.body && <div className="muted small">{x.body}</div>}</div>
            </li>
          );
        })}
        {active && <li className="run"><span className="ico"><Icon name="refresh" size={18} className="spin" /></span><div className="muted">Working…</div></li>}
      </ol>
    </section>
  );
}
