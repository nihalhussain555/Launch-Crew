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

export default function Settings() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const [stats, setStats] = useState(null);
  const [out, setOut] = useState(false);
  useEffect(() => { api.stats().then(setStats).catch(() => {}); }, []);

  return (
    <>
      <div className="page-head">
        <div><h1>Settings</h1><p className="muted">Your account, appearance and workspace usage in one place.</p></div>
        <Link to="/profile" className="btn ghost small"><Icon name="user" size={15} /> View profile</Link>
      </div>

      <div className="set-grid">
        <section className="card set-card">
          <h2>Account</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Display name</span><strong className="set-val">{user?.name || "Not set"}</strong></div>
            <div className="set-row"><span className="set-key">Email</span><strong className="set-val">{user?.email || "—"}</strong></div>
            <div className="set-row"><span className="set-key">Account ID</span><strong className="set-val mono small">{user?.id || "—"}</strong></div>
            <div className="set-row"><span className="set-key">Sign out</span>
              <span className="set-val"><button className="side-logout compact" onClick={() => setOut(true)}><Icon name="logout" size={15} /> Log out</button></span></div>
          </div>
          <p className="set-note">Your name and email come from your sign-in credentials. Contact support to change them.</p>
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
            <div className="set-row"><span className="set-key">Saved on</span><strong className="set-val">This device only</strong></div>
          </div>
          <p className="set-note">Light and dark are tuned separately — cards, borders and text all shift. Nothing else in your workspace changes.</p>
        </section>

        <section className="card set-card">
          <h2>Usage</h2>
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
          <h2>Help</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Product tour</span>
              <span className="set-val"><button className="btn ghost small" onClick={() => window.dispatchEvent(new Event("lc-tour-restart"))}><Icon name="refresh" size={15} /> Restart tour</button></span></div>
            <div className="set-row"><span className="set-key">Support</span>
              <span className="set-val"><a className="btn ghost small" href="mailto:hello@launchcrew.app"><Icon name="mail" size={15} /> Contact us</a></span></div>
            <div className="set-row"><span className="set-key">Data &amp; privacy</span>
              <span className="set-val"><Link className="btn ghost small" to="/legal/privacy"><Icon name="shield" size={15} /> Policies</Link></span></div>
          </div>
        </section>

        <section className="card set-card">
          <h2>Keyboard</h2>
          <div className="set-rows">
            <div className="set-row"><span className="set-key">Command palette</span><kbd className="set-val">Ctrl / ⌘ + K</kbd></div>
            <div className="set-row"><span className="set-key">Close any dialog</span><kbd className="set-val">Esc</kbd></div>
            <div className="set-row"><span className="set-key">Move through a rating</span><kbd className="set-val">Arrow keys</kbd></div>
          </div>
        </section>
      </div>

      <ConfirmModal open={out} onClose={() => setOut(false)} onConfirm={logout} danger confirmLabel="Log out"
        title="Log out?" message="You will need to sign in again to see your projects and runs." />
    </>
  );
}
