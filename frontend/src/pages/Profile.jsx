import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import ConfirmModal from "../components/ConfirmModal";
import Icon from "../components/Icon";
import ScoreRing from "../components/ScoreRing";
import { useTheme } from "../theme";
import { compact } from "../utils";

const THEMES = [["light", "sun", "Light"], ["dark", "moon", "Dark"]];

export default function Profile() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const [stats, setStats] = useState(null);
  const [out, setOut] = useState(false);

  useEffect(() => { api.stats().then(setStats).catch(() => {}); }, []);

  const initials = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();
  const emailDomain = (user?.email || "").split("@")[1] || "—";

  return (
    <>
      <div className="page-head">
        <div><h1>Profile</h1><p className="muted">Your account, workspace activity and appearance.</p></div>
        <div className="row"><Link to="/settings" className="btn ghost"><Icon name="gear" size={16} /> Settings</Link></div>
      </div>

      <section className="card profile-hero">
        <div className="avatar" aria-hidden="true">{initials}</div>
        <div style={{ minWidth: 0 }}>
          <h1>{user?.name || "You"}</h1>
          <p className="muted">{user?.email}</p>
          <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
            <span className="pill"><Icon name="user" size={13} /> Account owner</span>
            <span className="pill"><Icon name="mail" size={13} /> {emailDomain}</span>
          </div>
        </div>
      </section>

      <div className="set-grid">
        <section className="card set-card">
          <h2>Account</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Display name</span><strong className="set-val">{user?.name || "Not set"}</strong></div>
            <div className="set-row"><span className="set-key">Email</span><strong className="set-val">{user?.email || "—"}</strong></div>
            <div className="set-row"><span className="set-key">Account ID</span><strong className="set-val mono small">{user?.id || "—"}</strong></div>
          </div>
          <p className="set-note">Name and email come from your sign-in credentials. Use Settings for workspace preferences.</p>
        </section>

        <section className="card set-card">
          <h2>Workspace activity</h2>
          {!stats ? <div className="skeleton" style={{ height: 150 }} /> : (
            <div className="set-rows">
              <div className="set-row"><span className="set-key">Projects</span><strong className="set-val">{stats.projects}</strong></div>
              <div className="set-row"><span className="set-key">Runs</span><strong className="set-val">{stats.runs}</strong></div>
              <div className="set-row"><span className="set-key">Deployed pages</span><strong className="set-val">{stats.deployed}</strong></div>
              <div className="set-row"><span className="set-key">Tokens used</span><strong className="set-val">{compact(stats.tokens)}</strong></div>
              <div className="set-row"><span className="set-key">Avg readiness</span>
                <span className="set-val">{stats.avg_readiness == null ? <strong>—</strong> : <ScoreRing value={stats.avg_readiness} size={40} stroke={5} />}</span></div>
            </div>
          )}
        </section>

        <section className="card set-card">
          <h2>Appearance</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Theme</span>
              <span className="set-val"><div className="seg" role="group" aria-label="Theme">
                {THEMES.map(([id, icon, label]) => (
                  <button key={id} className={theme === id ? "on" : ""} onClick={() => setTheme(id)} aria-pressed={theme === id}>
                    <Icon name={icon} size={16} /> {label}
                  </button>
                ))}
              </div></span></div>
          </div>
          <p className="set-note">Your choice is saved on this device and applied the next time you open the app.</p>
        </section>

        <section className="card set-card">
          <h2>Session</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Signed in on</span><strong className="set-val">This browser</strong></div>
            <div className="set-row"><span className="set-key">Sign out</span>
              <span className="set-val"><button className="side-logout compact" onClick={() => setOut(true)}><Icon name="logout" size={15} /> Sign out</button></span></div>
          </div>
          <p className="set-note">Signing out clears the saved session token on this device.</p>
        </section>
      </div>

      <ConfirmModal open={out} onClose={() => setOut(false)} onConfirm={logout} danger confirmLabel="Sign out"
        title="Sign out of Launch Crew?" message="You will need to sign in again to see your projects and runs." />
    </>
  );
}
