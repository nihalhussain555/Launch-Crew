import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useToast } from "../toast";
import { safeNext } from "../utils";
import AuthBrand from "../components/AuthBrand";
import Icon from "../components/Icon";

export default function Login() {
  const { user, login } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const loc = useLocation();
  const [f, setF] = useState({ email: "", password: "" });
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const dest = safeNext(new URLSearchParams(loc.search).get("next"));
  if (user) return <Navigate to={dest} replace />;

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try { await login(f.email.trim(), f.password); toast("Welcome back", "success"); nav(dest, { replace: true }); }
    catch (ex) { setErr(ex.message || "Unable to sign in."); setBusy(false); }
  };

  return (
    <div className="auth-shell">
      <AuthBrand title="Welcome back to Launch Crew." subtitle="Sign in to pick up where your crew left off — and ship your next idea." />
      <div className="auth-panel">
        <form className="auth-card" onSubmit={submit} noValidate>
          <div><h2>Sign in</h2><p className="sub">Use the email and password you signed up with.</p></div>

          <div className="field">
            <label htmlFor="email">Email</label>
            <div className="with-icon">
              <span className="lead"><Icon name="mail" size={17} /></span>
              <input id="email" type="email" required autoComplete="email" value={f.email} onChange={set("email")} placeholder="you@company.com" data-autofocus />
            </div>
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="with-icon">
              <span className="lead"><Icon name="lock" size={17} /></span>
              <input id="password" type={show ? "text" : "password"} required autoComplete="current-password" value={f.password} onChange={set("password")} placeholder="••••••••" />
              <button type="button" className="icon-btn pw-toggle" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
                <Icon name={show ? "eyeOff" : "eye"} size={18} />
              </button>
            </div>
          </div>

          <div className="field-row">
            <span />
            <a className="forgot" href="mailto:hello@launchcrew.app?subject=Password%20reset">Forgot password?</a>
          </div>

          {err && <div className="error" role="alert">{err}</div>}
          <button className="btn primary big block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          <p className="auth-foot">Don't have an account? <Link to="/register">Create one</Link></p>
        </form>
      </div>
    </div>
  );
}
