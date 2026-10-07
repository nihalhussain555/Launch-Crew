import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "./Icon";

const KEY = "lc_tour_done";
/* Each step lists the elements it can point at, in priority order — the first one actually on
   screen wins, so the rail step falls back to the mobile menu button on narrow viewports. */
const STEPS = [
  { targets: ["[data-tour=nav]", "[data-tour=navToggle]"], title: "Your workspace lives here", body: "Dashboard, Projects, Templates and Settings are always one click away. The rail highlights where you are." },
  { targets: ["[data-tour=idea]"], title: "Start with one sentence", body: "Describe any idea and the crew — researcher, strategist, copywriter, designer, engineer, critic, audience panel — gets to work." },
  { targets: ["[data-tour=stats]"], title: "Track what matters", body: "Projects, runs, deployed pages, readiness and token spend, straight from your account." },
  { targets: ["[data-tour=search]"], title: "Everything on Ctrl / ⌘ K", body: "The command palette jumps to any page and lists your recent runs. Esc closes any dialog." },
  { targets: ["[data-tour=profile]"], title: "Account, theme and sign out", body: "Your profile, settings, help and sign out live in this menu. Dark mode is one click away in the rail." },
];

const onScreen = (el) => {
  if (!el) return false;
  const r = el.getBoundingClientRect();
  return r.width > 4 && r.height > 4 && r.right > 12 && r.left < window.innerWidth - 12 && r.bottom > 12 && r.top < window.innerHeight - 12;
};

const findTarget = (targets) => {
  for (const sel of targets) {
    const el = document.querySelector(sel);
    if (onScreen(el)) return el;
  }
  return null;
};

/** Guided first-run tour: spotlight + tooltip, skip / back / next, progress, persisted completion. */
export default function ProductTour() {
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);

  const finish = useCallback(() => { localStorage.setItem(KEY, "1"); setOpen(false); }, []);

  useEffect(() => {
    const start = () => {
      if (localStorage.getItem(KEY)) return;
      setI(0); setOpen(true);
    };
    const restart = () => { localStorage.removeItem(KEY); setI(0); setOpen(true); };
    window.addEventListener("lc-tour-start", start);
    window.addEventListener("lc-tour-restart", restart);
    // auto-open shortly after the first authenticated paint
    const t = setTimeout(start, 700);
    return () => { clearTimeout(t); window.removeEventListener("lc-tour-start", start); window.removeEventListener("lc-tour-restart", restart); };
  }, []);

  const step = STEPS[i];

  useLayoutEffect(() => {
    if (!open) return undefined;
    let raf = 0;
    const measure = () => {
      const el = findTarget(step.targets);
      if (!el) { setRect(null); return; }
      const r = el.getBoundingClientRect();
      setRect({ top: r.top - 8, left: r.left - 8, width: r.width + 16, height: r.height + 16 });
    };
    const anchor = findTarget(step.targets);
    if (anchor) anchor.scrollIntoView({ block: "center", behavior: "smooth" });
    measure();
    const onResize = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(measure); };
    window.addEventListener("resize", onResize);
    const id = setInterval(onResize, 260); // follow the smooth scroll
    return () => { window.removeEventListener("resize", onResize); clearInterval(id); cancelAnimationFrame(raf); };
  }, [open, i, step.targets]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") finish();
      if (e.key === "ArrowRight" && i < STEPS.length - 1) setI(i + 1);
      if (e.key === "ArrowLeft" && i > 0) setI(i - 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, i, finish]);

  if (!open) return null;

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const wide = vw > 720;
  // place the card beside the spotlight when there is room, otherwise dock it to the bottom
  let cardStyle;
  if (rect && wide) {
    const right = rect.left + rect.width + 18 + 330 < vw;
    const left = right ? rect.left + rect.width + 18 : Math.max(16, rect.left - 348);
    const top = Math.min(Math.max(16, rect.top), vh - 260);
    cardStyle = { left, top, width: 330 };
  }

  return createPortal(
    <>
      {rect && <div className="tour-spot" style={rect} aria-hidden="true" />}
      <div className={`tour-card ${cardStyle ? "" : "center"}`} style={cardStyle} role="dialog" aria-modal="true" aria-label="Product tour">
        <p className="tour-kicker">Product tour · {i + 1} of {STEPS.length}</p>
        <h3 className="tour-title">{step.title}</h3>
        <p className="tour-body">{step.body}</p>
        <div className="tour-dots" aria-hidden="true">
          {STEPS.map((s, n) => <i key={s.title} className={n === i ? "on" : n < i ? "done" : ""} />)}
        </div>
        <div className="tour-foot">
          <button className="tour-skip" onClick={finish}>Skip tour</button>
          <div className="row">
            {i > 0 && <button className="btn ghost small" onClick={() => setI(i - 1)}><Icon name="left" size={15} /> Back</button>}
            {i < STEPS.length - 1
              ? <button className="btn primary small" data-autofocus onClick={() => setI(i + 1)}>Next</button>
              : <button className="btn primary small" data-autofocus onClick={finish}>Finish</button>}
          </div>
        </div>
      </div>
    </>,
    document.body
  );
}
