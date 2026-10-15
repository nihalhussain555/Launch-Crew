import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useToast } from "../toast";
import score, { LABELS } from "../password-strength";
import AuthBrand from "../components/AuthBrand";
import Icon from "../components/Icon";

export default function ResetPassword() {
  const { logout } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [f, setF] = useState({ password: "", confirm: "" });
  const [show, setShow] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const level = useMemo(() => score(f.password), [f.password]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (f.password.length < 8) return setErr("Password must be at least 8 characters.");
    if (f.password !== f.confirm) return setErr("Passwords don't match.");
    setBusy(true);
    try {
      await api.resetPassword(token, f.password);
      // The server ends sessions minted before this password, so the token in this browser is dead
      // whether or not it belongs to the account being reset. Dropping it here saves a confusing
      // "invalid token" on the next page instead of a mystery 401 later.
      logout();
      toast("Password changed — sign in with the new one", "success");
      nav("/login", { replace: true });
    } catch (ex) {
      setErr(ex.message || "That reset link could not be used.");
      setBusy(false);
    }
  };

  const form = (
    <form className="auth-card" onSubmit={submit} noValidate>
      <div><h2>Choose a new password</h2><p className="sub">This link works once. After it, sign in with the password you set here.</p></div>

      <div className="field">
        <label htmlFor="password">New password</label>
        <div className="with-icon">
          <span className="lead"><Icon name="lock" size={17} /></span>
          <input id="password" type={show ? "text" : "password"} required autoComplete="new-password" value={f.password} onChange={set("password")} placeholder="At least 8 characters" data-autofocus />
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
        <label htmlFor="confirm">Confirm new password</label>
        <div className="with-icon">
          <span className="lead"><Icon name="lock" size={17} /></span>
          <input id="confirm" type={show ? "text" : "password"} required autoComplete="new-password" value={f.confirm} onChange={set("confirm")} placeholder="Re-enter your new password" />
        </div>
        {f.confirm && f.confirm !== f.password && <p className="field-hint">Passwords don't match yet.</p>}
      </div>

      {err && <div className="error" role="alert">{err}</div>}
      <button className="btn primary big block" disabled={busy}>{busy ? "Saving…" : "Set new password"}</button>
      <p className="auth-foot">Link expired? <Link to="/forgot-password">Ask for a new one</Link></p>
    </form>
  );

  // A link with no token in it never reached this page intact, so there is nothing to redeem.
  const broken = token.length < 16 && (
    <div className="auth-card">
      <div><h2>This link is not complete</h2><p className="sub">A reset link carries a token we cannot see until you open it in your browser. Copy the whole link, or ask for a new one.</p></div>
      <Link className="btn primary big block" to="/forgot-password">Ask for a new link</Link>
    </div>
  );

  return (
    <div className="auth-shell">
      <AuthBrand title="One link, one new password." subtitle="Reset links are single use and expire, so an old one cannot be replayed against your account." />
      <div className="auth-panel">{broken || form}</div>
    </div>
  );
}
