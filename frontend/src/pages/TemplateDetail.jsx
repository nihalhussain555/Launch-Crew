import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import IdeaForm from "../components/IdeaForm";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import { TEMPLATES, catIcon } from "../constants";
import { useStartRun } from "../hooks/useStartRun";
import { slugify } from "../utils";

const CREW = [
  { icon: "search", role: "Researcher", does: "Scans the space for the audience, pain points and how similar products position themselves." },
  { icon: "target", role: "Strategist", does: "Picks the sharpest angle and writes the promise the page should lead with." },
  { icon: "book", role: "Copywriter", does: "Drafts headline, benefit blocks, social proof and the call to action." },
  { icon: "layers", role: "Designer", does: "Turns the copy into a responsive, on-brand layout with real hierarchy." },
  { icon: "cpu", role: "Engineer", does: "Builds the page as a self-contained, production-ready HTML file." },
  { icon: "shield", role: "Critic + browser QA", does: "Runs the page in a real browser and fixes layout, contrast and link issues." },
  { icon: "user", role: "Audience panel", does: "Synthetic visitors react: first impression, objections, would-they-sign-up." },
  { icon: "rocket", role: "Launcher", does: "After your approval, deploys the page and drafts the launch kit." },
];

export default function TemplateDetail() {
  const { slug } = useParams();
  const [open, setOpen] = useState(false);
  const { start, busy } = useStartRun();
  const t = TEMPLATES.find((x) => slugify(x.title) === slug);

  if (!t) {
    return (
      <div className="page-head"><div><h1>Template not found</h1><p className="muted">It may have been renamed. The full gallery is one click away.</p></div>
        <Link to="/templates" className="btn primary"><Icon name="left" size={15} /> All templates</Link></div>
    );
  }

  const related = TEMPLATES.filter((x) => x.cat === t.cat && x.title !== t.title).slice(0, 3);
  const fallback = TEMPLATES.filter((x) => x.title !== t.title).slice(0, 3);
  const more = related.length ? related : fallback;

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/templates" className="muted small"><Icon name="left" size={13} /> Templates</Link>
          <h1>{t.title}</h1>
          <div className="row wrap" style={{ gap: 8 }}>
            <span className="pill"><Icon name={catIcon(t.cat)} size={13} /> {t.cat}</span>
            <span className="muted small">Ready to launch in one run</span>
          </div>
        </div>
        <div className="row">
          <button className="btn primary" onClick={() => setOpen(true)}><Icon name="rocket" size={16} /> Launch this idea</button>
        </div>
      </div>

      <section className="card">
        <h2>The idea</h2>
        <p className="lead-copy">{t.idea}</p>
        <p className="muted small">Edit the wording before you start — the crew builds exactly what you submit.</p>
      </section>

      <section className="card">
        <h2>Who works on it</h2>
        <p className="muted small">Eight specialised agents run in sequence, then review and revise before you ever see a result.</p>
        <ul className="crew-list">
          {CREW.map((c) => (
            <li key={c.role}>
              <span className="cap-ico"><Icon name={c.icon} size={19} /></span>
              <div><strong>{c.role}</strong><p className="muted small">{c.does}</p></div>
            </li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>What you get</h2>
        <div className="feat-grid">
          {[
            ["monitor", "A launch-ready page", "Responsive, self-contained HTML you can download or deploy."],
            ["shield", "Real browser checks", "Layout, contrast and links verified before approval."],
            ["user", "Audience reactions", "Scores, objections and one suggested improvement."],
            ["target", "Readiness score", "A 0–100 verdict with the reasoning behind it."],
            ["rocket", "Launch kit", "Three social posts and an email, drafted after deploy."],
            ["link", "Shareable preview", "Collect feedback from real people and turn it into a revision."],
          ].map(([icon, title, text]) => (
            <article className="feat-card" key={title}>
              <span className="cap-ico"><Icon name={icon} size={19} /></span>
              <div><h3>{title}</h3><p>{text}</p></div>
            </article>
          ))}
        </div>
      </section>

      <section>
        <div className="row between"><h2>More in this space</h2><Link to="/templates" className="muted small">Browse all <Icon name="arrowRight" size={14} /></Link></div>
        <div className="tpl-preview">
          {more.map((x) => (
            <Link to={`/templates/${slugify(x.title)}`} className="tpl-mini" key={x.title}>
              <div className="tpl-top"><strong>{x.title}</strong><span className="pill">{x.cat}</span></div>
              <span className="muted clamp">{x.idea}</span>
              <span className="chip">View details <Icon name="arrowRight" size={13} /></span>
            </Link>
          ))}
        </div>
      </section>

      <Modal open={open} onClose={() => setOpen(false)} title={t.title}>
        <p className="muted">Tweak the wording if you like, then start the crew.</p>
        <IdeaForm initial={t.idea} onSubmit={async (idea) => { if (await start(idea)) setOpen(false); }} busy={busy} showExamples={false} submitLabel="Launch this idea" rows={4} />
      </Modal>
    </>
  );
}
