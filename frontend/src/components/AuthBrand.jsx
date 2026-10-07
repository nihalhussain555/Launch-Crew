import LaunchCrewLogo from "./LaunchCrewLogo";
import Icon from "./Icon";

const POINTS = [
  ["cpu", "A crew of AI agents researches, writes and designs"],
  ["shield", "A real browser checks every page before it ships"],
  ["user", "A simulated audience reacts before your users do"],
  ["lock", "Nothing goes live without your approval"],
];

export default function AuthBrand({ title, subtitle }) {
  return (
    <aside className="auth-brand">
      <div className="side-brand" style={{ position: "relative", zIndex: 1 }}>
        <LaunchCrewLogo size={26} className="on-dark" />
      </div>
      <div className="auth-tag">
        <h1>{title}</h1>
        <p>{subtitle}</p>
        <ul className="auth-points">
          {POINTS.map(([icon, text]) => (
            <li key={text}><span className="cap-ico"><Icon name={icon} size={16} /></span>{text}</li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
