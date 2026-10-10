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
      {/* Decorative: the same brand mark, spun in 3D. Reduced motion still reads as a tilted composition. */}
      <div className="auth-3d" aria-hidden="true">
        <span className="logo3d">
          <span className="logo3d-glow" />
          <span className="logo3d-ring r1" />
          <span className="logo3d-ring r2" />
          <span className="logo3d-spin">
            <span className="logo3d-face front"><LaunchCrewLogo variant="icon" size={126} /></span>
            <span className="logo3d-face back"><LaunchCrewLogo variant="icon" size={126} /></span>
          </span>
          <span className="logo3d-shadow" />
        </span>
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
