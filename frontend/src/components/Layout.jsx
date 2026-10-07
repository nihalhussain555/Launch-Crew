import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useTheme } from "../theme";
import { useAuth } from "../auth";
import CommandPalette from "./CommandPalette";
import Icon from "./Icon";
import LaunchCrewLogo from "./LaunchCrewLogo";
import ProfileDropdown from "./ProfileDropdown";
import ProductTour from "./ProductTour";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "home" },
  { to: "/projects", label: "Projects", icon: "folder" },
  { to: "/templates", label: "Templates", icon: "sparkle" },
  { to: "/settings", label: "Settings", icon: "gear" },
];
const THEME_ICON = { system: "monitor", light: "sun", dark: "moon" };

export default function Layout() {
  const { user } = useAuth();
  const { theme, cycle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const loc = useLocation();

  useEffect(() => setNavOpen(false), [loc.pathname]);
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const name = user?.name || user?.email || "You";

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to content</a>
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="side-brand">
          <Link to="/dashboard" className="side-logo"><LaunchCrewLogo size={28} /></Link>
          <span className="brand-tag">Build · Automate · Launch</span>
        </div>

        <div className="side-scroll">
          <p className="side-label">Workspace</p>
          <nav className="side-nav" aria-label="Main" data-tour="nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={({ isActive }) => `side-link ${isActive ? "active" : ""}`}>
                <Icon name={n.icon} className="side-ico" /> {n.label}
              </NavLink>
            ))}
          </nav>
          <p className="side-label">Quick actions</p>
          <div className="side-quick">
            <Link to="/dashboard" className="btn primary block small"><Icon name="rocket" size={15} /> New idea</Link>
            <button className="btn ghost block small" onClick={() => setPalette(true)}><Icon name="search" size={15} /> Command palette</button>
          </div>
        </div>

        <div className="side-foot">
          <Link to="/profile" className="user-chip">
            <span className="avatar" aria-hidden="true">{name.trim().charAt(0).toUpperCase()}</span>
            <span className="side-user"><strong>{user?.name || "You"}</strong><span className="muted small">{user?.email}</span></span>
          </Link>
          <div className="side-actions">
            <button className="icon-btn" onClick={cycle} title={`Theme: ${theme} (click to change)`} aria-label={`Theme: ${theme}`}>
              <Icon name={THEME_ICON[theme]} />
            </button>
          </div>
        </div>
      </aside>
      {navOpen && <div className="scrim" onClick={() => setNavOpen(false)} />}

      <div className="main-col">
        <header className="topbar">
          <button className="icon-btn hamburger" onClick={() => setNavOpen(true)} aria-label="Open menu" data-tour="navToggle"><Icon name="menu" /></button>
          <button className="search-btn" onClick={() => setPalette(true)} data-tour="search">
            <Icon name="search" size={16} /> <span>Search or jump to…</span>
            <kbd>Ctrl K</kbd>
          </button>
          <button className="icon-btn top-theme" onClick={cycle} title={`Theme: ${theme} (click to change)`} aria-label={`Theme: ${theme}`}>
            <Icon name={THEME_ICON[theme]} />
          </button>
          <ProfileDropdown />
        </header>
        <main className="page" id="main" tabIndex={-1}><Outlet /></main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <ProductTour />
    </div>
  );
}
