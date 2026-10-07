import Icon from "./Icon";

/** The "AI is working" indicator — replaces bare spinners with a crew-aware progress cue. */
export default function AiWorking({ label = "The crew is working", detail = true }) {
  return (
    <div className="ai-working" role="status" aria-live="polite">
      <span className="ai-orb" aria-hidden="true"><Icon name="sparkle" size={19} /></span>
      <div className="ai-meta">
        <strong>{label}</strong>
        {detail && <span className="muted small">Researcher · Strategist · Copywriter · Designer · Engineer · Critic · Audience panel</span>}
        <div className="ai-lines" aria-hidden="true"><i /><i /><i /></div>
      </div>
    </div>
  );
}
