import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import IdeaForm from "../components/IdeaForm";
import Modal from "../components/Modal";
import { catIcon } from "../constants";
import { STATUS_SHORT, STATUS_TONE, templateWizardLink, useTemplates } from "../hooks/useTemplates";
import { useStartRun } from "../hooks/useStartRun";
import { useToast } from "../toast";

/** The requests a card cannot honour on its own, in one honest line: what needs keys, what is source to start. */
function waitingFor(t) {
  const groups = [["needs-external-setup", "Needs your account or keys"], ["scaffold", "Source you start yourself"]];
  return groups
    .map(([state, words]) => {
      const names = t.features.filter((f) => f.status === state).map((f) => f.label);
      return names.length ? `${words}: ${names.join(", ")}` : "";
    })
    .filter(Boolean);
}

export default function Templates() {
  const [cat, setCat] = useState("All");
  const [pick, setPick] = useState(null);
  const toast = useToast();
  const { start, busy } = useStartRun();
  const { catalog, list, error, load, numberOf } = useTemplates();

  const groups = catalog ? (cat === "All" ? catalog.categories : [cat]) : [];

  // The brief comes back from the registry rather than being rebuilt here, so the spec a card launches
  // with is the spec the run stores - including the template key the page's own wording follows.
  const launch = async (idea) => {
    try {
      const d = await api.templateDetail(pick.key);
      if (await start(idea, d.spec)) setPick(null);
    } catch (e) {
      toast(e.message, "error");
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Professional templates</h1>
          <p className="muted">Twenty site shapes, each one a real brief: the layout, the content blocks and
            the requests a run builds from.</p>
        </div>
        <div className="row wrap">
          <Link to="/new" className="btn ghost"><Icon name="plus" size={15} /> Write your own brief</Link>
          <Link to="/dashboard" className="btn ghost"><Icon name="chat" size={15} /> Just an idea</Link>
        </div>
      </div>

      {error && <ErrorState title="The gallery did not load" message={error} retry={load} back="/dashboard" />}

      {!catalog && !error && <p className="muted" role="status">Reading the template registry from the server…</p>}

      {catalog && (
        <>
          <div className="row wrap" role="group" aria-label="Category">
            {["All", ...catalog.categories].map((c) => (
              <button key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}
                aria-pressed={cat === c}>{c}</button>
            ))}
          </div>
          <p className="muted small">{catalog.note}</p>

          {groups.map((c) => (
            <section className="section" key={c}>
              <div className="section-head">
                <h2><Icon name={catIcon(c)} size={17} /> {c}</h2>
              </div>
              <div className="grid-cards">
                {list.filter((t) => t.category === c).map((t) => (
                  <article className="card template-card" key={t.key}>
                    <div className="tpl-top">
                      <span className="pill"><Icon name={catIcon(t.category)} size={13} /> {t.category}</span>
                      <span className="tpl-num" aria-hidden="true">{numberOf(t.key)}</span>
                    </div>
                    <strong>{t.label}</strong>
                    <span className="muted small">{t.industries.join(" · ")}</span>
                    <p className="muted small clamp">{t.summary}</p>
                    <div className="tpl-brief">
                      <span className="small">{t.style_label} layout · a {t.business_label.toLowerCase()} site</span>
                      <span className="row wrap">
                        {t.blocks.map((b) => <span key={b.key} className="chip" title={b.carries}>{b.label}</span>)}
                      </span>
                    </div>
                    {waitingFor(t).map((line) => <p className="muted small" key={line}>{line}</p>)}
                    <div className="row wrap">
                      <button className="btn primary small" onClick={() => setPick(t)}>
                        <Icon name="rocket" size={14} /> Use template
                      </button>
                      <Link className="btn ghost small" to={templateWizardLink(t)}>
                        <Icon name="sliders" size={14} /> Refine in the wizard
                      </Link>
                      <Link className="btn ghost small" to={`/templates/${t.key}`}>
                        Details <Icon name="arrowRight" size={14} />
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </>
      )}

      <Modal open={!!pick} onClose={() => setPick(null)} title={pick ? `${pick.label}: what the crew builds` : ""}>
        {pick && (
          <>
            <p className="muted">Edit the idea if you like, then launch the crew. The layout, blocks and
              requests of this card go with it.</p>
            <IdeaForm
              initial={pick.idea}
              onSubmit={launch}
              busy={busy}
              showExamples={false}
              submitLabel="Launch this idea"
              rows={4}
            />
            <p className="muted small">
              <span className={`pill ${STATUS_TONE[pick.status]}`}>{STATUS_SHORT[pick.status] || pick.status}</span>{" "}
              {pick.notes[0]}
            </p>
            <p className="muted small">
              Full list of what this card needs from you, and the page it composes to, on the{" "}
              <Link to={`/templates/${pick.key}`}>template details page</Link>.
            </p>
          </>
        )}
      </Modal>
    </>
  );
}
