import { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import LaunchCrewLogo from "./LaunchCrewLogo";
import Icon from "./Icon";
import { useAuth } from "../auth";
import { useTheme } from "../theme";

const LINKS = [
  { to: "/", label: "Home", end: true },
  { to: "/about", label: "About" },
  { to: "/templates", label: "Templates" },
];
const THEME_ICON = { system: "monitor", light: "sun", dark: "moon" };

export default function PublicNavbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const { user } = useAuth();
  const { theme, cycle } = useTheme();
  const nav = useNavigate();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`site-header ${scrolled ? "scrolled" : ""}`}>
      <div className="nav-inner">
        <Link to="/" aria-label="Launch Crew home">
          <LaunchCrewLogo size={26} />
        </Link>
        <nav className="site-links" aria-label="Primary">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="site-cta">
          {user ? (
            <button className="btn primary nav-cta" onClick={() => nav("/dashboard")}>
              Open dashboard <Icon name="arrowRight" size={16} />
            </button>
          ) : (
            <>
              <Link to="/login" className="nav-link">Sign in</Link>
              <Link to="/register" className="btn primary nav-cta">Get started <Icon name="arrowRight" size={16} /></Link>
            </>
          )}
          <button className="icon-btn" onClick={cycle} title={`Theme: ${theme}`} aria-label={`Theme: ${theme}`} style={{ border: "1px solid var(--border)" }}>
            <Icon name={THEME_ICON[theme]} />
          </button>
          <button className="m-toggle" onClick={() => setOpen(true)} aria-label="Open menu"><Icon name="menu" /></button>
        </div>
      </div>

      {open && <div className="m-backdrop" onClick={() => setOpen(false)} />}
      <div className={`m-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="row between" style={{ marginBottom: 12 }}>
          <LaunchCrewLogo size={22} />
          <button className="icon-btn" onClick={() => setOpen(false)} aria-label="Close menu"><Icon name="close" /></button>
        </div>
        {LINKS.map((l) => (
          <NavLink key={l.to} to={l.to} end={l.end} className="nav-link" onClick={() => setOpen(false)}>{l.label}</NavLink>
        ))}
        {user ? (
          <button className="btn primary block" onClick={() => { setOpen(false); nav("/dashboard"); }}>Open dashboard</button>
        ) : (
          <>
            <Link to="/login" className="btn ghost block" onClick={() => setOpen(false)}>Sign in</Link>
            <Link to="/register" className="btn primary block" onClick={() => setOpen(false)}>Get started</Link>
          </>
        )}
      </div>
    </header>
  );
}
