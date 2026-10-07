import { Link } from "react-router-dom";
import Icon from "../components/Icon";

const VALUES = [
  { icon: "cpu", title: "Agents, not autocomplete", text: "Each step is handled by a specialist agent with its own role, tools and standards." },
  { icon: "shield", title: "Verified before shipped", text: "A real browser and a critic pass stand between your idea and a live URL." },
  { icon: "user", title: "Audience-first", text: "We simulate how people react, so you learn what to fix before real users see it." },
  { icon: "lock", title: "Human in the loop", text: "You approve every deploy. Automation accelerates the work; it never replaces your call." },
];

const FAQ = [
  ["What is Launch Crew?", "An AI workspace that turns a one-line idea into a tested, launch-ready landing page using a crew of specialist agents."],
  ["Do I need to know how to code or design?", "No. The crew handles research, copy, design and front-end build; you review and approve."],
  ["Can I share the result with others?", "Yes. Every run can produce a public preview link where visitors leave ratings and feedback."],
  ["Will anything go live without my approval?", "No. Deployment is always gated behind your explicit approval."],
];

export default function About() {
  return (
    <>
      <section className="hero anim-up">
        <span className="eyebrow"><Icon name="sparkle" size={15} /> About Launch Crew</span>
        <h1 className="hero-title">We automate the messy middle<br />of <span className="grad-text">launching</span>.</h1>
        <p className="hero-sub">Launching a product idea means research, positioning, copy, design, a build, QA and feedback. Launch Crew runs that entire loop for you — with you staying in control of what ships.</p>
      </section>

      <section className="section">
        <div className="grid2" style={{ alignItems: "center" }}>
          <div><h2 style={{ marginTop: 0 }}>What is Launch Crew?</h2>
            <p className="muted">Launch Crew is an AI launch workspace. You describe a product idea in a sentence; a coordinated crew of agents researches the market, writes and designs a landing page, checks it in a real browser, and gets a simulated audience to react — then scores how launch-ready it is.</p>
            <p className="muted">It is built for founders, indie makers and teams who want to validate and ship small products fast, without hiring a full crew themselves.</p></div>
          <div className="card hero-card"><h3 style={{ marginTop: 0 }}>Our mission</h3>
            <p className="muted" style={{ marginBottom: 0 }}>Make going from idea to a tested, live product a matter of minutes — and raise the quality bar by automating the checks most people skip.</p></div>
        </div>
      </section>

      <section className="section" id="capabilities">
        <div className="section-head"><h2>What we're building</h2><p>A platform that takes an idea all the way to a defensible launch.</p></div>
        <div className="cap-grid">
          {VALUES.map((v) => (
            <article className="cap-card" key={v.title}>
              <span className="cap-ico"><Icon name={v.icon} size={22} /></span>
              <h3>{v.title}</h3><p>{v.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head"><h2>Technology &amp; innovation</h2><p>Real orchestration, real tooling, real verification.</p></div>
        <div className="feat-grid">
          <article className="feat-card"><span className="cap-ico"><Icon name="workflow" size={20} /></span><div><h3>Multi-agent orchestration</h3><p>A graph coordinates researcher, strategist, copywriter, designer, engineer, critic, audience panel and launcher agents.</p></div></article>
          <article className="feat-card"><span className="cap-ico"><Icon name="globe" size={20} /></span><div><h3>Browser-based QA</h3><p>Generated pages are rendered and checked in a headless browser, not just eyeballed in a preview.</p></div></article>
          <article className="feat-card"><span className="cap-ico"><Icon name="chart" size={20} /></span><div><h3>Readiness scoring</h3><p>Every run is scored across quality dimensions so you can compare iterations objectively.</p></div></article>
          <article className="feat-card"><span className="cap-ico"><Icon name="mail" size={20} /></span><div><h3>Feedback loop</h3><p>Share a live link, collect real ratings and comments, and turn them into a targeted revision.</p></div></article>
        </div>
      </section>

      <section className="section" id="faq">
        <div className="section-head"><h2>Frequently asked questions</h2></div>
        <div className="stack" style={{ maxWidth: 760, margin: "0 auto" }}>
          {FAQ.map(([q, a]) => (
            <details className="card" key={q} style={{ padding: "14px 18px" }}>
              <summary style={{ cursor: "pointer", fontWeight: 600 }}>{q}</summary>
              <p className="muted" style={{ marginBottom: 0 }}>{a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="cta-band">
        <div className="cta-inner">
          <h2>Try the crew on your next idea</h2>
          <p>One sentence in. A tested, launch-ready page out.</p>
          <Link to="/register" className="btn primary xl">Get started free <Icon name="arrowRight" size={18} /></Link>
        </div>
      </section>
    </>
  );
}
