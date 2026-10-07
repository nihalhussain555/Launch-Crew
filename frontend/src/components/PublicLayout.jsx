import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import PublicNavbar from "./PublicNavbar";
import PublicFooter from "./PublicFooter";

export default function PublicLayout() {
  const { pathname, hash } = useLocation();

  useEffect(() => {
    if (!hash) { window.scrollTo(0, 0); return; }
    const el = document.getElementById(hash.slice(1));
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    else window.scrollTo(0, 0);
  }, [pathname, hash]);

  return (
    <div className="landing">
      <a className="skip" href="#main">Skip to content</a>
      <PublicNavbar />
      <main id="main" tabIndex={-1}><Outlet /></main>
      <PublicFooter />
    </div>
  );
}
