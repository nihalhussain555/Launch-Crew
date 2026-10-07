const MAP = {
  queued: ["Queued", "warn"], running: ["Running", "warn"], awaiting_approval: ["Awaiting approval", "warn"],
  deploying: ["Deploying", "warn"], deployed: ["Deployed", "ok"], failed: ["Failed", "err"],
};
const LIVE = new Set(["queued", "running", "deploying"]);

export default function StatusPill({ status }) {
  const [label, tone] = MAP[status] || [status, ""];
  const dot = LIVE.has(status) ? "live" : tone === "ok" ? "on" : tone === "err" ? "err" : "";
  return (
    <span className={`pill ${tone}`}>
      <span className={`dot ${dot}`} aria-hidden="true" /> {label}
    </span>
  );
}
