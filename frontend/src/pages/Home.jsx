import { Link } from "react-router-dom";
import Icon from "../components/Icon";
import { TEMPLATES, catIcon } from "../constants";
import { slugify } from "../utils";

const CAPS = [
  { icon: "cpu", title: "AI Agents", text: "A crew of specialist agents research, position, write, design and engineer your page." },
  { icon: "workflow", title: "Workflow Automation", text: "One idea in, an orchestrated multi-step run out — no manual hand-offs." },
  { icon: "shield", title: "Real Browser QA", text: "A headless browser checks the built page and reports issues before you ship." },
  { icon: "user", title: "Audience Panel", text: "A simulated audience reacts first, so you see objections and sign-up intent early." },
  { icon: "chart", title: "Readiness Analytics", text: "Every run is scored for launch readiness with a critic report you can act on." },
  { icon: "rocket", title: "Approval-gated Deploy", text: "Nothing ships without you. Deploy, then share a live link for real feedback." },
];

const STEPS = [
  { n: "01", title: "Choose", text: "Start from an idea or a professionally designed template." },
  { n: "02", title: "Build", text: "The agent crew generates a tested, launch-ready landing page." },
  { n: "03", title: "Automate", text: "Browser checks, a critic and an audience panel refine it in a loop." },
  { n: "04", title: "Launch", text: "Approve, deploy, and collect feedback from a shareable preview." },
];

const FEATURES = [
  { icon: "target", title: "Launch readiness score", text: "A single, explainable score with per-check pass / warn / fail detail." },
  { icon: "book", title: "Critic report", text: "An agent reviews copy, design and engineering, then suggests fixes." },
  { icon: "layers", title: "Live preview", text: "Inspect the generated page in desktop and mobile viewports with screenshots." },
  { icon: "mail", title: "Feedback inbox", text: "Share a public link; visitors rate the page and their notes become a revision." },
  { icon: "workflow", title: "Revision loop", text: "Turn any feedback into a targeted AI revision — copy, layout or design." },
  { icon: "lock", title: "You stay in control", text: "Deployment is gated behind your explicit approval, every time." },
];

export default function Home() {
  return (
    <>
      <section className="hero anim-up">
        <span className="eyebrow"><Icon name="sparkle" size={15} /> The AI launch workspace</span>
        <h1 className="hero-title">Build. Automate. <span className="grad-text">Launch.</span></h1>
        <p className="hero-sub">Launch Crew turns a single idea into a tested, launch-ready page — a crew of AI agents researches, writes, designs, checks it in a real browser, and gets a simulated audience to react before you ship.</p>
        <div className="hero-cta">
          <Link to="/register" className="btn primary xl">Get started free <Icon name="arrowRight" size={18} /></Link>
          <Link to="/templates" className="btn xl">Explore templates</Link>
        </div>
        <p className="hero-note">No credit card required · Free to start</p>
      </section>

      <section className="hero-visual anim-up">
        <div className="appwin" role="img" aria-label="Preview of a Launch Crew run">
          <div className="appwin-bar"><i /><i /><i /><span>launchcrew · run #4821</span></div>
          <div className="appwin-body">
            <div className="stack">
              <div className="mock-grad" />
              <div className="mock-line w90" />
              <div className="mock-line w70" />
              <div className="mock-line w45" />
              <div className="row wrap" style={{ gap: 8, marginTop: 6 }}>
                <span className="pill ok">Browser checks passed</span>
                <span className="pill">Audience: 7 would sign up</span>
              </div>
            </div>
            <div className="appwin-side">
              <div className="stat-num" style={{ fontSize: 30 }}><span className="grad-text">92</span></div>
              <span className="muted small">Readiness</span>
            </div>
          </div>
        </div>
      </section>

      <section className="section" id="capabilities">
        <div className="section-head"><h2>Everything you need to go from idea to launch</h2><p>A complete, automated pipeline — not a blank page and a prayer.</p></div>
        <div className="cap-grid">
          {CAPS.map((c) => (
            <article className="cap-card" key={c.title}>
              <span className="cap-ico"><Icon name={c.icon} size={22} /></span>
              <h3>{c.title}</h3><p>{c.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section" id="how">
        <div className="section-head"><h2>How it works</h2><p>Four steps, fully automated by the crew.</p></div>
        <div className="steps">
          {STEPS.map((s) => (
            <div className="step" key={s.n}><span className="num">{s.n}</span><h3>{s.title}</h3><p>{s.text}</p></div>
          ))}
        </div>
      </section>

      <section className="section" id="features">
        <div className="section-head"><h2>Built for shipping real launches</h2><p>The tools that make the difference between a mockup and a launch.</p></div>
        <div className="feat-grid">
          {FEATURES.map((f) => (
            <article className="feat-card" key={f.title}>
              <span className="cap-ico"><Icon name={f.icon} size={20} /></span>
              <div><h3>{f.title}</h3><p>{f.text}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section className="section" id="templates">
        <div className="section-head"><h2>Start from a template</h2><p>Professionally crafted starting points across categories.</p></div>
        <div className="tpl-preview">
          {TEMPLATES.slice(0, 6).map((t) => (
            <Link to={`/templates/${slugify(t.title)}`} className="tpl-mini" key={t.title}>
              <div className="tpl-top">
                <span className="cap-ico" aria-hidden="true"><Icon name={catIcon(t.cat)} size={19} /></span>
                <span className="pill">{t.cat}</span>
              </div>
              <strong>{t.title}</strong>
              <span className="muted clamp">{t.idea}</span>
              <span className="chip">View details <Icon name="arrowRight" size={13} /></span>
            </Link>
          ))}
        </div>
        <div className="section-cta-row"><Link to="/templates" className="btn ghost">View all templates <Icon name="arrowRight" size={16} /></Link></div>
      </section>

      <section className="cta-band">
        <div className="cta-inner">
          <h2>Ready to launch your next idea?</h2>
          <p>Give Launch Crew one sentence and watch a tested, launch-ready page come out the other side.</p>
          <Link to="/register" className="btn primary xl">Get started free <Icon name="arrowRight" size={18} /></Link>
        </div>
      </section>
    </>
  );
}
