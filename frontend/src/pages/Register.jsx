import { useMemo, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useToast } from "../toast";
import { safeNext } from "../utils";
import AuthBrand from "../components/AuthBrand";
import Icon from "../components/Icon";

const LABELS = ["Too short", "Weak", "Fair", "Strong", "Excellent"];

// Deterministic 0–4 score: length + character classes, no external lib.
function score(pw) {
  if (!pw) return 0;
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(4, pw.length < 8 ? 1 : s);
}

export default function Register() {
  const { user, register } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const loc = useLocation();
  const [f, setF] = useState({ name: "", email: "", password: "", confirm: "" });
  const [show, setShow] = useState(false);
  const [agree, setAgree] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const level = useMemo(() => score(f.password), [f.password]);
  const dest = safeNext(new URLSearchParams(loc.search).get("next"));
  if (user) return <Navigate to={dest} replace />;

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (f.name.trim().length < 2) return setErr("Please enter your full name.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email.trim())) return setErr("Please enter a valid email address.");
    if (f.password.length < 8) return setErr("Password must be at least 8 characters.");
    if (f.password !== f.confirm) return setErr("Passwords don't match.");
    if (!agree) return setErr("Please accept the terms to continue.");
    setBusy(true);
    try {
      await register(f.email.trim(), f.password, f.name.trim());
      toast("Account created — welcome aboard", "success");
      nav(dest, { replace: true });
    } catch (ex) {
      setErr(ex.message || "Unable to create your account.");
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <AuthBrand title="Create your Launch Crew account." subtitle="One workspace for research, copy, design, code and launch — run by your AI crew." />
      <div className="auth-panel">
        <form className="auth-card" onSubmit={submit} noValidate>
          <div><h2>Create account</h2><p className="sub">Just a name, an email and a password — that's your workspace.</p></div>

          <div className="field">
            <label htmlFor="name">Full name</label>
            <div className="with-icon">
              <span className="lead"><Icon name="user" size={17} /></span>
              <input id="name" required autoComplete="name" value={f.name} onChange={set("name")} placeholder="Ada Lovelace" data-autofocus />
            </div>
          </div>
          <div className="field">
            <label htmlFor="email">Work email</label>
            <div className="with-icon">
              <span className="lead"><Icon name="mail" size={17} /></span>
              <input id="email" type="email" required autoComplete="email" value={f.email} onChange={set("email")} placeholder="you@company.com" />
            </div>
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div className="with-icon">
              <span className="lead"><Icon name="lock" size={17} /></span>
              <input id="password" type={show ? "text" : "password"} required autoComplete="new-password" value={f.password} onChange={set("password")} placeholder="At least 8 characters" />
              <button type="button" className="icon-btn pw-toggle" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide password" : "Show password"}>
                <Icon name={show ? "eyeOff" : "eye"} size={18} />
              </button>
            </div>
            {f.password && (
              <>
                <div className="strength" role="img" aria-label={`Password strength: ${LABELS[level]}`}>
                  {[1, 2, 3, 4].map((i) => <i key={i} className={level >= i ? `on${level}` : ""} />)}
                </div>
                <p className="strength-label">{LABELS[level]}</p>
              </>
            )}
          </div>
          <div className="field">
            <label htmlFor="confirm">Confirm password</label>
            <div className="with-icon">
              <span className="lead"><Icon name="lock" size={17} /></span>
              <input id="confirm" type={show ? "text" : "password"} required autoComplete="new-password" value={f.confirm} onChange={set("confirm")} placeholder="Re-enter your password" />
            </div>
            {f.confirm && f.confirm !== f.password && <p className="field-hint">Passwords don't match yet.</p>}
          </div>

          <label className="terms">
            <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
            <span>I agree to the <Link to="/legal/terms">Terms</Link>, <Link to="/legal/privacy">Privacy Policy</Link> and <Link to="/legal/cookies">Cookie Policy</Link>.</span>
          </label>

          {err && <div className="error" role="alert">{err}</div>}
          <button className="btn primary big block" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
          <p className="auth-foot">Already have an account? <Link to="/login">Sign in</Link></p>
        </form>
      </div>
    </div>
  );
}
