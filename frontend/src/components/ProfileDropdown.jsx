import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import Icon from "./Icon";

/** Avatar button + menu in the app topbar. Closes on outside click, Esc or route change. */
export default function ProfileDropdown() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const name = user?.name || user?.email || "You";
  const initial = name.trim().charAt(0).toUpperCase();
  const close = () => setOpen(false);
  const go = (to) => { close(); nav(to); };
  const signOut = () => { close(); logout(); };

  return (
    <div className="dropdown" ref={ref}>
      <button className="dd-trigger" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open} data-tour="profile">
        <span className="avatar" aria-hidden="true">{initial}</span>
        <span className="dd-name">{name}</span>
        <Icon name="chevronDown" size={16} className={open ? "flip" : ""} />
      </button>

      {open && (
        <div className="dd-menu" role="menu">
          <div className="dd-head">
            <span className="avatar" aria-hidden="true">{initial}</span>
            <div style={{ minWidth: 0 }}><strong>{user?.name || "You"}</strong><span className="block">{user?.email}</span></div>
          </div>
          <div className="dd-sep" />
          <p className="dd-label">Account</p>
          <button className="dd-item" role="menuitem" onClick={() => go("/profile")}><Icon name="user" size={17} /> Your profile</button>
          <button className="dd-item" role="menuitem" onClick={() => go("/settings")}><Icon name="gear" size={17} /> Settings</button>
          <div className="dd-sep" />
          <p className="dd-label">Support</p>
          <button className="dd-item" role="menuitem" onClick={() => { close(); window.dispatchEvent(new Event("lc-tour-restart")); }}>
            <Icon name="refresh" size={17} /> Restart product tour
          </button>
          <Link className="dd-item" role="menuitem" to="/about" onClick={close}><Icon name="book" size={17} /> About Launch Crew</Link>
          <a className="dd-item" role="menuitem" href="mailto:hello@launchcrew.app?subject=Support%20request"><Icon name="help" size={17} /> Help &amp; support</a>
          <div className="dd-sep" />
          <button className="dd-item danger" role="menuitem" onClick={signOut}><Icon name="logout" size={17} /> Sign out</button>
        </div>
      )}
    </div>
  );
}
