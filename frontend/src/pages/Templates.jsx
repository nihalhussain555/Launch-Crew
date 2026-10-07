import { useState } from "react";
import { Link } from "react-router-dom";
import IdeaForm from "../components/IdeaForm";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import { CATEGORIES, TEMPLATES, catIcon } from "../constants";
import { useStartRun } from "../hooks/useStartRun";
import { slugify } from "../utils";

export default function Templates() {
  const [cat, setCat] = useState("All");
  const [pick, setPick] = useState(null);
  const { start, busy } = useStartRun();
  const shown = TEMPLATES.filter((t) => cat === "All" || t.cat === cat);

  return (
    <>
      <div className="page-head">
        <div><h1>Idea templates</h1><p className="muted">Pick a starting point, tweak the wording, and launch the crew.</p></div>
        <Link to="/dashboard" className="btn ghost"><Icon name="plus" size={15} /> Start from a blank idea</Link>
      </div>
      <div className="row wrap" role="group" aria-label="Category">
        {CATEGORIES.map((c) => <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)} aria-pressed={cat === c}>{c}</button>)}
      </div>
      <div className="grid-cards">
        {shown.map((t) => (
          <article className="card template-card" key={t.title}>
            <div className="tpl-top">
              <span className="cap-ico" aria-hidden="true"><Icon name={catIcon(t.cat)} size={20} /></span>
              <span className="pill">{t.cat}</span>
            </div>
            <strong>{t.title}</strong>
            <span className="muted small clamp">{t.idea}</span>
            <div className="row wrap">
              <button className="btn primary small" onClick={() => setPick(t)}><Icon name="rocket" size={14} /> Use template</button>
              <Link className="btn ghost small" to={`/templates/${slugify(t.title)}`}>Details <Icon name="arrowRight" size={14} /></Link>
            </div>
          </article>
        ))}
      </div>
      <Modal open={!!pick} onClose={() => setPick(null)} title={pick ? pick.title : ""}>
        <p className="muted">Edit the idea if you like, then start the crew.</p>
        <IdeaForm initial={pick?.idea || ""} onSubmit={start} busy={busy} showExamples={false} submitLabel="Launch this idea" rows={4} />
      </Modal>
    </>
  );
}
