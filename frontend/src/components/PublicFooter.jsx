import { Link } from "react-router-dom";
import LaunchCrewLogo from "./LaunchCrewLogo";

const COLS = [
  { h: "Product", links: [["Overview", "/"], ["How it works", { pathname: "/", hash: "#how" }], ["Features", { pathname: "/", hash: "#features" }], ["Templates", "/templates"]] },
  { h: "Company", links: [["About", "/about"], ["Contact", "mailto:hello@launchcrew.app"]] },
  { h: "Resources", links: [["Help & support", "mailto:hello@launchcrew.app"], ["Report a bug", "mailto:hello@launchcrew.app?subject=Bug%20report"]] },
  { h: "Legal", links: [["Privacy", "/legal/privacy"], ["Terms", "/legal/terms"], ["Cookies", "/legal/cookies"]] },
];

export default function PublicFooter() {
  return (
    <footer className="site-footer">
      <div className="foot-inner">
        <div className="foot-grid">
          <div className="foot-brand">
            <LaunchCrewLogo size={26} />
            <p>Build, automate and launch AI-powered products from one workspace — with a crew of agents that test before you ship.</p>
          </div>
          {COLS.map((c) => (
            <div className="foot-col" key={c.h}>
              <h4>{c.h}</h4>
              {c.links.map(([label, to]) => (
                typeof to === "string" && to.startsWith("mailto:")
                  ? <a key={label} href={to}>{label}</a>
                  : <Link key={label} to={to}>{label}</Link>
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="foot-bottom">
        <span>© {new Date().getFullYear()} Launch Crew. All rights reserved.</span>
        <span>Build · Automate · Launch</span>
      </div>
    </footer>
  );
}
