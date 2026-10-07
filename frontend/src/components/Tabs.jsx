export default function Tabs({ tabs, active, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={active === t.id} className={`tab ${active === t.id ? "on" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}{t.badge ? <span className={`badge ${t.tone || ""}`}>{t.badge}</span> : null}
        </button>
      ))}
    </div>
  );
}