import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import ConfirmModal from "../components/ConfirmModal";
import Icon from "../components/Icon";
import { useTheme } from "../theme";
import { compact } from "../utils";

const THEMES = [["system", "monitor", "System"], ["light", "sun", "Light"], ["dark", "moon", "Dark"]];

export default function Settings() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const [stats, setStats] = useState(null);
  const [out, setOut] = useState(false);
  useEffect(() => { api.stats().then(setStats).catch(() => {}); }, []);

  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><p className="muted">Account, appearance and usage.</p></div></div>
      <div className="grid-cards">
        <section className="card">
          <h2>Account</h2>
          <div className="kv"><span className="muted">Name</span><strong>{user?.name || "-"}</strong></div>
          <div className="kv"><span className="muted">Email</span><strong>{user?.email}</strong></div>
          <button className="btn ghost danger-text" onClick={() => setOut(true)}>Log out</button>
        </section>
        <section className="card">
          <h2>Appearance</h2>
          <div className="seg" role="group" aria-label="Theme">
            {THEMES.map(([id, icon, label]) => <button key={id} className={theme === id ? "on" : ""} onClick={() => setTheme(id)}><Icon name={icon} size={16} /> {label}</button>)}
          </div>
          <p className="muted small">“System” follows your device setting.</p>
        </section>
        <section className="card">
          <h2>Usage</h2>
          {!stats ? <div className="skeleton" style={{ height: 80 }} /> : (
            <>
              <div className="kv"><span className="muted">Projects</span><strong>{stats.projects}</strong></div>
              <div className="kv"><span className="muted">Runs</span><strong>{stats.runs}</strong></div>
              <div className="kv"><span className="muted">Deployed</span><strong>{stats.deployed}</strong></div>
              <div className="kv"><span className="muted">Tokens used</span><strong>{compact(stats.tokens)}</strong></div>
            </>
          )}
        </section>
        <section className="card">
          <h2>Help</h2>
          <div className="kv"><span className="muted">Product tour</span>
            <button className="btn ghost small" onClick={() => window.dispatchEvent(new Event("lc-tour-restart"))}><Icon name="refresh" size={15} /> Restart tour</button></div>
          <div className="kv"><span className="muted">Support</span>
            <a className="btn ghost small" href="mailto:hello@launchcrew.app"><Icon name="mail" size={15} /> Contact us</a></div>
        </section>
        <section className="card">
          <h2>Shortcuts</h2>
          <div className="kv"><span className="muted">Command palette</span><kbd>Ctrl / ⌘ + K</kbd></div>
          <div className="kv"><span className="muted">Close any dialog</span><kbd>Esc</kbd></div>
        </section>
      </div>
      <ConfirmModal open={out} onClose={() => setOut(false)} onConfirm={logout} confirmLabel="Log out" title="Log out?" message="You will need to sign in again to see your projects." />
    </>
  );
}