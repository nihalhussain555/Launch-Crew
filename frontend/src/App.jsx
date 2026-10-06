import { Link, Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Home from "./pages/Home";
import Login from "./pages/Login";
import RunDetail from "./pages/RunDetail";

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="center muted">Loading…</div>;
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  const { user, logout } = useAuth();
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">🚀 Launch Crew</Link>
        {user && (
          <div className="row">
            <span className="muted small">{user.email}</span>
            <button className="btn ghost" onClick={logout}>Log out</button>
          </div>
        )}
      </header>
      <main className="container">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Protected><Home /></Protected>} />
          <Route path="/runs/:runId" element={<Protected><RunDetail /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  );
}
