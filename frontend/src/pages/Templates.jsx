import { useState } from "react";
import { Link } from "react-router-dom";
import IdeaForm from "../components/IdeaForm";
import Icon from "../components/Icon";
import Modal from "../components/Modal";
import { CATEGORIES, TEMPLATES, catIcon, templateSpec, templateWizardLink } from "../constants";
import { useStartRun } from "../hooks/useStartRun";
import { useStyleRegistry } from "../hooks/useStyleRegistry";
import { slugify } from "../utils";

export default function Templates() {
  const [cat, setCat] = useState("All");
  const [pick, setPick] = useState(null);
  const { start, busy } = useStartRun();
  const { reg, styleOf } = useStyleRegistry();
  const shown = TEMPLATES.filter((t) => cat === "All" || t.cat === cat);

  return (
    <>
      <div className="page-head">
        <div><h1>Idea templates</h1><p className="muted">Pick a starting point, tweak the wording, and launch the crew.</p></div>
        <div className="row wrap">
          <Link to="/new" className="btn ghost"><Icon name="plus" size={15} /> Write your own brief</Link>
          <Link to="/dashboard" className="btn ghost"><Icon name="chat" size={15} /> Just an idea</Link>
        </div>
      </div>
      <div className="row wrap" role="group" aria-label="Category">
        {CATEGORIES.map((c) => <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)} aria-pressed={cat === c}>{c}</button>)}
      </div>
      <p className="muted small">
        {reg
          ? "Each card carries a real brief: the site type, the design style and the sections it launches with."
          : "Each card carries a real brief - the style names load from the design registry."}
      </p>
      <div className="grid-cards">
        {shown.map((t) => (
          <article className="card template-card" key={t.title}>
            <div className="tpl-top">
              <span className="cap-ico" aria-hidden="true"><Icon name={catIcon(t.cat)} size={20} /></span>
              <span className="pill">{t.cat}</span>
            </div>
            <strong>{t.title}</strong>
            <span className="muted small clamp">{t.idea}</span>
            <div className="tpl-brief">
              <span className="small">
                {styleOf(t.style)?.label || t.style}
                {reg ? ` · ${reg.business_types.find((b) => b.key === t.business)?.label || t.business}` : ""}
              </span>
              {t.sections.length > 0 && (
                <span className="row wrap">{t.sections.map((s) => <span key={s} className="chip">{s}</span>)}</span>
              )}
            </div>
            <div className="row wrap">
              <button className="btn primary small" onClick={() => setPick(t)}><Icon name="rocket" size={14} /> Use template</button>
              <Link className="btn ghost small" to={templateWizardLink(t)}><Icon name="sliders" size={14} /> Refine in the wizard</Link>
              <Link className="btn ghost small" to={`/templates/${slugify(t.title)}`}>Details <Icon name="arrowRight" size={14} /></Link>
            </div>
          </article>
        ))}
      </div>
      <Modal open={!!pick} onClose={() => setPick(null)} title={pick ? pick.title : ""}>
        <p className="muted">Edit the idea if you like, then start the crew. The site type, style and sections of this card are sent with it.</p>
        <IdeaForm
          initial={pick?.idea || ""}
          onSubmit={async (idea) => { if (await start(idea, templateSpec(pick))) setPick(null); }}
          busy={busy}
          showExamples={false}
          submitLabel="Launch this idea"
          rows={4}
        />
        {pick && (
          <p className="muted small">
            Built as {styleOf(pick.style)?.label || "a style from the registry"}.
            {" "}Not what you want? <Link to={templateWizardLink(pick)}>Change the brief first</Link>.
          </p>
        )}
      </Modal>
    </>
  );
}
