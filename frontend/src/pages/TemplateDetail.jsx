import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import IdeaForm from "../components/IdeaForm";
import Modal from "../components/Modal";
import PreviewFrame from "../components/PreviewFrame";
import { catIcon } from "../constants";
import { STATUS_SHORT, STATUS_TONE, templateWizardLink, useTemplates } from "../hooks/useTemplates";
import { useStartRun } from "../hooks/useStartRun";

// Where a feature's work happens, in the catalog's own words for the surface.
const SURFACE = { page: "in the page", server: "in the backend", database: "in your database",
                  integration: "with an outside account" };
const CORE = ["features", "faq", "cta"];

export default function TemplateDetail() {
  const { slug } = useParams();                       // the registry key, e.g. "restaurant-cafe"
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");
  const [pv, setPv] = useState(null);
  const [pvErr, setPvErr] = useState("");
  const [open, setOpen] = useState(false);
  const { start, busy } = useStartRun();
  const { catalog, list, error, load, numberOf, inCategory } = useTemplates();

  useEffect(() => {
    let dead = false;
    setDetail(null); setErr("");
    api.templateDetail(slug)
      .then((d) => { if (!dead) setDetail(d); })
      .catch((e) => { if (!dead) setErr(e.message); });
    return () => { dead = true; };
  }, [slug]);

  // The preview is the builder's own output for this composition. It arrives after the brief and fails on
  // its own terms: the page describes the template either way.
  const loadPreview = useCallback(() => {
    setPv(null); setPvErr("");
    api.templatePreview(slug).then(setPv).catch((e) => setPvErr(e.message));
  }, [slug]);
  useEffect(loadPreview, [loadPreview]);

  if (error) return <ErrorState title="The gallery did not load" message={error} retry={load}
                                back="/templates" backLabel="All templates" />;
  if (err) {
    return (
      <div className="page-head">
        <div><h1>Template not found</h1><p className="muted">{err}</p></div>
        <Link to="/templates" className="btn primary"><Icon name="left" size={15} /> All templates</Link>
      </div>
    );
  }
  if (!detail || !catalog) return <p className="muted" role="status">Reading this template from the registry…</p>;

  const t = detail.template;
  const spec = detail.spec;
  const implied = detail.sections_built.filter((s) => !CORE.includes(s) && !t.sections.includes(s));
  const more = (inCategory(t.category).filter((x) => x.key !== t.key).length
    ? inCategory(t.category) : list).filter((x) => x.key !== t.key).slice(0, 3);
  const waiting = t.features.filter((f) => f.status !== "generated");
  const ready = t.features.filter((f) => f.status === "generated");

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/templates" className="muted small"><Icon name="left" size={13} /> Templates</Link>
          <div className="tpl-title">
            <span className="tpl-num lg" aria-hidden="true">{numberOf(t.key)}</span>
            <h1>{t.label}</h1>
          </div>
          <div className="row wrap" style={{ gap: 8 }}>
            <span className="pill"><Icon name={catIcon(t.category)} size={13} /> {t.category}</span>
            <span className="muted small">{t.industries.join(" · ")}</span>
          </div>
        </div>
        <div className="row">
          <Link className="btn ghost" to={templateWizardLink(t)}><Icon name="sliders" size={15} /> Refine in the wizard</Link>
          <button className="btn primary" onClick={() => setOpen(true)}><Icon name="rocket" size={16} /> Launch this brief</button>
        </div>
      </div>

      <section className="card">
        <h2>What this page is</h2>
        <p className="lead-copy">{t.summary}</p>
        <p className="muted small">Built as a {t.business_label.toLowerCase()} site in the {t.style_label}
          layout — {t.style_blurb}</p>
      </section>

      <section className="card">
        <h2>The brief the crew receives</h2>
        <p className="lead-copy">{t.idea}</p>
        <dl className="kv">
          <div><dt>Written for</dt><dd>{t.audience}</dd></div>
          <div><dt>Tone</dt><dd>{t.tone}</dd></div>
          <div><dt>Pages</dt><dd>{spec.pages.join(", ")}</dd></div>
          <div><dt>Asks for</dt><dd>{spec.features.join(", ")}</dd></div>
        </dl>
        <div className="tpl-brief">
          <span className="small">
            The page is built in this order: {detail.sections_built.join(", ")} — the three core blocks
            always, then this card&apos;s own ({t.sections.join(", ")})
            {implied.length > 0 && <> and {implied.join(", ")}, which a {t.business_label.toLowerCase()}{" "}
              site in the {t.style_label} layout brings with it</>}.
          </span>
          <span className="row wrap">
            {t.blocks.map((b) => <span key={b.key} className="chip" title={b.carries}>{b.label}</span>)}
          </span>
        </div>
        <p className="muted small">Change any of it in the wizard before launching — the card sets the
          starting point, not the finished page.</p>
      </section>

      <section className="card">
        <h2>Content blocks on the page</h2>
        <p className="muted small">Every block below is one the page builder has rendering code for,
          filled by the crew's copy pass for this business.</p>
        <ul className="block-list">
          {t.blocks.map((b) => (
            <li key={b.key}><strong>{b.label}</strong><span className="muted small">{b.carries}</span></li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h2>What works now, and what needs you</h2>
        <p className="muted small">These statuses are the feature catalog&apos;s own, read from the server.
          A request is not built until you start it in the workspace and approve the change.</p>
        <ul className="cap-rows">
          {t.features.map((f) => (
            <li key={f.key}>
              <div className="cap-row-head">
                <strong>{f.label}</strong>
                <span className={`pill ${STATUS_TONE[f.status]}`}>{STATUS_SHORT[f.status] || f.status}</span>
                {f.needs.length > 0 && <span className="muted small">{f.needs.map((n) => SURFACE[n] || n).join(", ")}</span>}
              </div>
              {f.status !== "generated" && (
                <ul className="cap-detail">
                  {f.setup.map((s, i) => <li key={i}>{i + 1}. {s}</li>)}
                  {f.env.length > 0 && <li className="env">Environment variables: {f.env.map((v) => <code key={v}>{v}</code>)}</li>}
                  {f.limits && <li className="limits">{f.limits}</li>}
                </ul>
              )}
            </li>
          ))}
        </ul>
        {ready.length === 0
          ? <p className="muted small">Nothing on this card runs on its own: each request ships as wired
              interfaces plus the setup steps above, and does nothing until you connect an account or start
              the source.</p>
          : waiting.length > 0 && <p className="muted small">{ready.map((f) => f.label).join(", ")} work in
              the published page. The rest stay scaffolding until you connect them.</p>}
      </section>

      <section className="card">
        <h2>What you still have to supply</h2>
        {t.notes.length
          ? <ul className="note-list">{t.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          : <EmptyState icon="check" title="Nothing owed on this card"
                        text="Its blocks and features all exist in the builder." />}
      </section>

      <section>
        <div className="row between wrap">
          <h2>The page this composes to</h2>
          <span className="muted small">{t.blocks.length} blocks · {t.style_label} layout</span>
        </div>
        {pv && <p className="muted small">{pv.note}</p>}
        {pvErr && <ErrorState title="The sample page did not build" message={pvErr} retry={loadPreview} />}
        <PreviewFrame html={pv?.html || ""} loading={!pv && !pvErr} />
      </section>

      <section>
        <div className="row between"><h2>More in this category</h2>
          <Link to="/templates" className="muted small">Browse all <Icon name="arrowRight" size={14} /></Link></div>
        <div className="tpl-preview">
          {more.map((x) => (
            <Link to={`/templates/${x.key}`} className="tpl-mini" key={x.key}>
              <div className="tpl-top">
                <strong>{x.label}</strong>
                <span className="tpl-num" aria-hidden="true">{numberOf(x.key)}</span>
              </div>
              <span className="muted clamp">{x.summary}</span>
              <span className="chip">View details <Icon name="arrowRight" size={13} /></span>
            </Link>
          ))}
        </div>
      </section>

      <Modal open={open} onClose={() => setOpen(false)} title={t.label}>
        <p className="muted">Tweak the wording if you like, then start the crew. The layout, blocks and
          requests of this card are sent with it.</p>
        <IdeaForm
          initial={t.idea}
          onSubmit={async (idea) => { if (await start(idea, spec)) setOpen(false); }}
          busy={busy}
          showExamples={false}
          submitLabel="Launch this idea"
          rows={4}
        />
        <p className="muted small">Different brief? <Link to={templateWizardLink(t)}>Open it in the
          creation wizard</Link>.</p>
      </Modal>
    </>
  );
}
