import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth";
import Icon from "./components/Icon";
import Layout from "./components/Layout";
import PublicLayout from "./components/PublicLayout";
import About from "./pages/About";
import Dashboard from "./pages/Dashboard";
import Home from "./pages/Home";
import Legal from "./pages/Legal";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import ProjectDetail from "./pages/ProjectDetail";
import Projects from "./pages/Projects";
import PublicPreview from "./pages/PublicPreview";
import Register from "./pages/Register";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";
import Templates from "./pages/Templates";
import TemplateDetail from "./pages/TemplateDetail";

function Protected({ children }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="center muted"><Icon name="refresh" size={18} className="spin" /> Loading your workspace…</div>;
  if (user) return children;
  const next = encodeURIComponent(`${loc.pathname}${loc.search}`);
  return <Navigate to={`/login?next=${next}`} replace />;
}

export default function App() {
  return (
    <Routes>
      {/* public shareable preview — no app chrome, no login */}
      <Route path="/p/:token" element={<PublicPreview />} />

      {/* marketing + auth */}
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/about" element={<About />} />
        <Route path="/legal/:slug" element={<Legal />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
      </Route>

      {/* authenticated product */}
      <Route element={<Protected><Layout /></Protected>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
        <Route path="/templates" element={<Templates />} />
        <Route path="/templates/:slug" element={<TemplateDetail />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/runs/:runId" element={<RunDetail />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
