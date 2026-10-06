import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth";

export default function Login() {
  const { user, login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ email: "", password: "", name: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try { mode === "login" ? await login(f.email, f.password) : await register(f.email, f.password, f.name); }
    catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <form className="card narrow" onSubmit={submit}>
      <h1>{mode === "login" ? "Welcome back" : "Create your account"}</h1>
      <p className="muted">One idea in. A researched, designed, checked landing page out.</p>
      {mode === "register" && <label>Name<input value={f.name} onChange={set("name")} autoComplete="name" /></label>}
      <label>Email<input type="email" required value={f.email} onChange={set("email")} autoComplete="email" /></label>
      <label>Password<input type="password" required minLength={8} maxLength={72} value={f.password} onChange={set("password")}
        autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
      {err && <div className="error" role="alert">{err}</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Log in" : "Sign up"}</button>
      <button type="button" className="btn link" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(""); }}>
        {mode === "login" ? "No account? Sign up" : "Have an account? Log in"}
      </button>
    </form>
  );
}
