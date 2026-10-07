import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import ConfirmModal from "../components/ConfirmModal";
import Icon from "../components/Icon";
import ScoreRing from "../components/ScoreRing";
import { useTheme } from "../theme";
import { compact } from "../utils";

const THEMES = [["system", "monitor", "System"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]];

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

      <div className="profile-grid">
        <section className="card">
          <h2>Account</h2>
          <div className="kv"><span className="muted">Display name</span><strong>{user?.name || "Not set"}</strong></div>
          <div className="kv"><span className="muted">Email</span><strong>{user?.email || "—"}</strong></div>
          <div className="kv"><span className="muted">Account ID</span><strong className="mono small">{user?.id || "—"}</strong></div>
          <p className="muted small">Name and email are managed with your account credentials. Use Settings for workspace preferences.</p>
        </section>

        <section className="card">
          <h2>Workspace activity</h2>
          {!stats ? <div className="skeleton" style={{ height: 120 }} /> : (
            <>
              <div className="kv"><span className="muted">Projects</span><strong>{stats.projects}</strong></div>
              <div className="kv"><span className="muted">Runs</span><strong>{stats.runs}</strong></div>
              <div className="kv"><span className="muted">Deployed pages</span><strong>{stats.deployed}</strong></div>
              <div className="kv"><span className="muted">Tokens used</span><strong>{compact(stats.tokens)}</strong></div>
              <div className="kv"><span className="muted">Avg readiness</span>
                <strong>{stats.avg_readiness == null ? "—" : <ScoreRing value={stats.avg_readiness} size={40} stroke={5} />}</strong>
              </div>
            </>
          )}
        </section>

        <section className="card">
          <h2>Appearance</h2>
          <div className="seg" role="group" aria-label="Theme">
            {THEMES.map(([id, icon, label]) => (
              <button key={id} className={theme === id ? "on" : ""} onClick={() => setTheme(id)} aria-pressed={theme === id}>
                <Icon name={icon} size={16} /> {label}
              </button>
            ))}
          </div>
          <p className="muted small">“System” follows your device setting. Your choice is saved on this device.</p>
        </section>

        <section className="card">
          <h2>Session</h2>
          <p className="muted small">Signed in on this browser. Signing out clears your local session token.</p>
          <div className="row wrap">
            <button className="btn ghost danger-text" onClick={() => setOut(true)}><Icon name="logout" size={16} /> Sign out</button>
            <Link to="/settings" className="btn ghost">All settings</Link>
          </div>
        </section>
      </div>

      <ConfirmModal open={out} onClose={() => setOut(false)} onConfirm={logout} confirmLabel="Sign out"
        title="Sign out of Launch Crew?" message="You will need to sign in again to see your projects and runs." />
    </>
  );
}
