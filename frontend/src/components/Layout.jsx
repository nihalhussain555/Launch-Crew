import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import CommandPalette from "./CommandPalette";
import ConfirmModal from "./ConfirmModal";
import Icon from "./Icon";
import LaunchCrewLogo from "./LaunchCrewLogo";
import ProfileDropdown from "./ProfileDropdown";
import ProductTour from "./ProductTour";
import { compact } from "../utils";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "home" },
  { to: "/projects", label: "Projects", icon: "folder" },
  { to: "/templates", label: "Templates", icon: "sparkle" },
  { to: "/settings", label: "Settings", icon: "gear" },
];
const THEME_ICON = { light: "sun", dark: "moon" };
const STATUS_LABEL = {
  queued: "Queued", running: "Running", awaiting_approval: "Needs approval",
  deploying: "Deploying", deployed: "Deployed", failed: "Failed",
};
const STATUS_TONE = { deployed: "ok", failed: "err", awaiting_approval: "warn" };
const STATUS_DOT = { queued: "live", running: "live", deploying: "live", deployed: "on", failed: "err", awaiting_approval: "warn" };

export default function Layout() {
  const { user, logout } = useAuth();
  const { theme, cycle } = useTheme();
  const [navOpen, setNavOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [out, setOut] = useState(false);
  const [stats, setStats] = useState(null);
  const loc = useLocation();

  useEffect(() => setNavOpen(false), [loc.pathname]);
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Sidebar panels read the same aggregate the dashboard uses; refreshed on navigation.
  useEffect(() => {
    let alive = true;
    api.stats().then((s) => { if (alive) setStats(s); }).catch(() => { if (alive) setStats(null); });
    return () => { alive = false; };
  }, [loc.pathname]);

  const runs = (stats?.recent_runs || []).slice(0, 4);
  const pending = runs.filter((r) => r.status === "awaiting_approval").length;

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

          <p className="side-label">Latest runs</p>
          <div className="side-runs">
            {!stats && [0, 1, 2].map((i) => <div key={i} className="skeleton side-run-skel" />)}
            {stats && runs.length === 0 && <p className="side-empty">No runs yet. Launch an idea from the dashboard and it will show up here.</p>}
            {runs.map((r) => (
              <Link key={r.id} to={`/runs/${r.id}`} className="side-run" title={r.idea}>
                <span className={`pill ${STATUS_TONE[r.status] || ""}`}>
                  <span className={`dot ${STATUS_DOT[r.status] || ""}`} aria-hidden="true" /> {STATUS_LABEL[r.status] || r.status}
                </span>
                <span className="side-run-idea">{r.idea}</span>
                {typeof r.score === "number" && <span className="side-run-score">{r.score}</span>}
              </Link>
            ))}
          </div>
        </div>

        <div className="side-foot">
          <p className="side-label">Workspace usage</p>
          <dl className="side-stats">
            <div><dt>Projects</dt><dd>{stats ? stats.projects : "–"}</dd></div>
            <div><dt>Runs</dt><dd>{stats ? stats.runs : "–"}</dd></div>
            <div><dt>Deployed</dt><dd>{stats ? stats.deployed : "–"}</dd></div>
            <div><dt>Tokens</dt><dd>{stats ? compact(stats.tokens) : "–"}</dd></div>
          </dl>
          <div className="side-help">
            <button className="btn ghost block small" onClick={() => window.dispatchEvent(new Event("lc-tour-restart"))}>
              <Icon name="help" size={15} /> Restart product tour
            </button>
            {pending > 0 && (
              <Link to={`/runs/${runs.find((r) => r.status === "awaiting_approval").id}`} className="side-pending">
                <Icon name="alert" size={15} /> {pending} run{pending > 1 ? "s" : ""} waiting on you
              </Link>
            )}
          </div>
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
