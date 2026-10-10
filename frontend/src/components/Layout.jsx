import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import CommandPalette from "./CommandPalette";
import ConfirmModal from "./ConfirmModal";
import Icon from "./Icon";
import LaunchCrewLogo from "./LaunchCrewLogo";
import ProfileDropdown from "./ProfileDropdown";
import ProductTour from "./ProductTour";

/** Every entry here is a real route in App.jsx, backed by a live endpoint. */
const NAV_GROUPS = [
  { label: "AI development", items: [
    { to: "/dashboard", label: "AI Agent Studio", icon: "cpu" },
    { to: "/projects", label: "Projects", icon: "folder" },
    { to: "/workflows", label: "Agent Workflows", icon: "workflow" },
    { to: "/chat", label: "AI Chat", icon: "chat" },
    { to: "/templates", label: "Templates", icon: "sparkle" },
  ] },
  { label: "Build & ship", items: [
    { to: "/workspace", label: "Code Workspace", icon: "code" },
    { to: "/versions", label: "Version History", icon: "layers" },
    { to: "/quality", label: "Security & Quality", icon: "shield" },
    { to: "/deployments", label: "Deployments", icon: "rocket" },
  ] },
  { label: "Manage", items: [
    { to: "/integrations", label: "Integrations", icon: "key" },
    { to: "/analytics", label: "Analytics & Usage", icon: "chart" },
    { to: "/settings", label: "Settings", icon: "gear" },
    { to: "/profile", label: "Profile", icon: "user" },
  ] },
];
const THEME_ICON = { light: "sun", dark: "moon" };

export default function Layout() {
  const { logout } = useAuth();
  const { theme, cycle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [out, setOut] = useState(false);
  const loc = useLocation();

  useEffect(() => setNavOpen(false), [loc.pathname]);
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to content</a>
      <aside className={`sidebar ${navOpen ? "open" : ""}`}>
        <div className="side-brand">
          <Link to="/dashboard" className="side-logo"><LaunchCrewLogo size={28} /></Link>
          <span className="brand-tag">Build · Automate · Launch</span>
        </div>

        <div className="side-scroll" data-tour="nav">
          {NAV_GROUPS.map((g) => (
            <nav key={g.label} className="side-nav" aria-label={g.label}>
              <p className="side-label">{g.label}</p>
              {g.items.map((n) => (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => `side-link ${isActive ? "active" : ""}`}>
                  <Icon name={n.icon} className="side-ico" /> {n.label}
                </NavLink>
              ))}
            </nav>
          ))}
        </div>

        <div className="side-foot">
          <button className="side-logout" onClick={() => setOut(true)}><Icon name="logout" size={16} /> Log out</button>
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
          <button className="icon-btn top-theme" onClick={cycle} title={`Theme: ${theme} (click to change)`} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            <Icon name={THEME_ICON[theme] || "sun"} />
          </button>
          <ProfileDropdown onSignOut={() => setOut(true)} />
        </header>
        <main className="page" id="main" tabIndex={-1}><Outlet /></main>
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <ProductTour />
      <ConfirmModal open={out} onClose={() => setOut(false)} onConfirm={logout} danger confirmLabel="Log out"
        title="Log out?" message="You will need to sign in again to see your projects and runs." />
    </div>
  );
}
