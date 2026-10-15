import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import AuthBrand from "../components/AuthBrand";
import Icon from "../components/Icon";

// Two shapes of answer, because the server tells us which one it is: a link that was mailed, and a
// link written to the server's own log on a deployment with no mail service. Saying "check your
// inbox" in the second case would send someone hunting for an email that was never going to arrive.
const TITLES = { email: "Check your inbox", server_log: "No mail service on this server" };

export default function ForgotPassword() {
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") || "");
  const [sent, setSent] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) return setErr("Please enter a valid email address.");
    setBusy(true);
    try {
      setSent(await api.forgotPassword(email.trim()));
    } catch (ex) {
      setErr(ex.message || "Unable to start a password reset right now.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <AuthBrand title="Lost your password?" subtitle="Ask for a reset link, choose a new password, and you are back at your desk in a minute." />
      <div className="auth-panel">
        {sent ? (
          <div className="auth-card">
            <div><h2>Reset requested</h2><p className="sub">For {email.trim()}.</p></div>
            <div className={`sent${sent.channel === "server_log" ? " log" : ""}`} role="status">
              <b>{TITLES[sent.channel] || "Reset link"}</b>
              <span>{sent.message}</span>
            </div>
            <div className="field-row">
              <button className="btn ghost" onClick={() => setSent(null)}>Use another email</button>
              <Link className="forgot" to="/login">Back to sign in</Link>
            </div>
          </div>
        ) : (
          <form className="auth-card" onSubmit={submit} noValidate>
            <div><h2>Forgot password</h2><p className="sub">Enter the email you signed up with and we will get a reset link to you.</p></div>

            <div className="field">
              <label htmlFor="email">Email</label>
              <div className="with-icon">
                <span className="lead"><Icon name="mail" size={17} /></span>
                <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" data-autofocus />
              </div>
            </div>

            {err && <div className="error" role="alert">{err}</div>}
            <button className="btn primary big block" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
            <p className="auth-foot">Remembered it after all? <Link to="/login">Sign in</Link></p>
          </form>
        )}
      </div>
    </div>
  );
}
