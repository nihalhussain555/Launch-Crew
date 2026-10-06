const ICON = { researcher: "🔎", strategist: "🧭", copywriter: "✍️", designer: "🎨", engineer: "🛠️", critic: "🧐", launcher: "🚀" };
const cap = (s = "") => s.charAt(0).toUpperCase() + s.slice(1);

function describe(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "agent_started": return { icon: ICON[d.agent] || "🤖", title: `${cap(d.agent)} started`, tone: "run" };
        case "agent_message":
      if (d.agent === "you") return { icon: "💬", title: "You requested a change", body: d.message, tone: "run" };
      if (d.agent === "system") return { icon: "⚠️", title: "System notice", body: d.message, tone: "warn" };
      return { icon: "✅", title: `${cap(d.agent)} finished`, body: d.message, meta: d.tokens ? `${d.tokens} tokens` : "", tone: "ok" };
    case "tool_call": return { icon: "🔧", title: `${cap(d.agent)} used ${d.tool}`, body: d.args?.query || d.url, tone: "tool" };
    case "rate_limited": return { icon: "⏳", title: "Rate limited — retrying", body: d.message, tone: "warn" };
    case "check_results": return { icon: "📋", title: `Browser checks (review ${d.iteration})`,
      body: `${d.summary.errors} error(s), ${d.summary.warnings} warning(s) of ${d.summary.total} checks`, tone: d.summary.errors ? "warn" : "ok" };
    case "critic_feedback": return { icon: "🧐", title: "Critic feedback", body: d.summary, tone: "warn" };
    case "screenshot_ready": return { icon: "📸", title: `Screenshot ready (${d.viewport})`, tone: "tool" };
    case "awaiting_approval": return { icon: "🛑", title: "Waiting for your approval", body: d.message, tone: "warn" };
    case "deployed": return { icon: "🎉", title: "Deployed", body: d.url, tone: "ok" };
    case "failed": return { icon: "❌", title: "Run failed", body: d.error, tone: "err" };
    default: return { icon: "•", title: ev.type, tone: "" };
  }
}

export default function AgentTrace({ events, connected, status }) {
  const active = ["queued", "running", "deploying"].includes(status);
  return (
    <section className="card">
      <div className="row between">
        <h2>Agent trace</h2>
        <span className={`pill ${connected ? "ok" : active ? "warn" : ""}`}>{connected ? "● live" : active ? "reconnecting…" : "idle"}</span>
      </div>
      {events.length === 0 && <div className="muted">{active ? "Waiting for the first agent…" : "No events."}</div>}
      <ol className="timeline">
        {events.filter((e) => e.type !== "screenshot_ready").map((ev) => {
          const x = describe(ev);
          return (
            <li key={ev.seq} className={x.tone}>
              <span className="ico">{x.icon}</span>
              <div><strong>{x.title}</strong> {x.meta && <span className="muted small">· {x.meta}</span>}
                {x.body && <div className="muted small">{x.body}</div>}</div>
            </li>
          );
        })}
        {active && <li className="run"><span className="ico spin">⟳</span><div className="muted">Working…</div></li>}
      </ol>
    </section>
  );
}
