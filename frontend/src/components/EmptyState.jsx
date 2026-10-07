import Icon from "./Icon";

/** Centred empty state. `icon` is a name from the custom Icon set (no emoji). */
export default function EmptyState({ icon = "sparkle", title, text, action }) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true"><Icon name={icon} size={26} strokeWidth={1.5} /></div>
      <h3>{title}</h3>
      {text && <p className="muted">{text}</p>}
      {action}
    </div>
  );
}
