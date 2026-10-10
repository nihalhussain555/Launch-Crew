export const EXAMPLES = [
  "A habit tracker for night-shift workers",
  "A meal-prep planner for busy parents",
  "A language-exchange app for retirees",
];

export const TEMPLATES = [
  { cat: "SaaS", title: "Invoice reminders", idea: "An invoice reminder tool for freelancers that politely chases late payments" },
  { cat: "SaaS", title: "Receipt scanner", idea: "A receipt scanner for small business owners that sorts expenses for tax season" },
  { cat: "Health", title: "Night-shift habits", idea: "A habit tracker for night-shift workers" },
  { cat: "Health", title: "Micro-meditation", idea: "A 3-minute meditation app for people with anxiety at work" },
  { cat: "Education", title: "Language exchange", idea: "A language-exchange app for retirees who want to practise with native speakers" },
  { cat: "Education", title: "Math coach", idea: "An AI math practice coach for middle-school students that explains mistakes kindly" },
  { cat: "Creators", title: "Clip finder", idea: "A tool that finds the best short clips in long podcast episodes for creators" },
  { cat: "Creators", title: "Commission manager", idea: "A commission manager for digital artists to track requests, payments and deadlines" },
  { cat: "Local", title: "Café loyalty", idea: "A digital loyalty card for independent coffee shops with no app download" },
  { cat: "Local", title: "Dog walkers", idea: "A booking and live-tracking service for neighbourhood dog walkers" },
  { cat: "Productivity", title: "Focus rooms", idea: "A virtual coworking space for remote workers who struggle to focus alone" },
  { cat: "Productivity", title: "Inbox zero", idea: "An email triage assistant for busy founders that drafts replies in their voice" },
];
export const CATEGORIES = ["All", ...Array.from(new Set(TEMPLATES.map((t) => t.cat)))];

/** One custom glyph per category — used instead of emoji across the gallery. */
export const CAT_ICON = {
  SaaS: "layers",
  Health: "shield",
  Education: "book",
  Creators: "sparkle",
  Local: "globe",
  Productivity: "workflow",
};
export const catIcon = (cat) => CAT_ICON[cat] || "sparkle";

/** The six on-demand crew agents that measure the live page. Order is the order the orchestrator runs them in. */
export const AUDITS = [
  { kind: "security", icon: "lock", label: "Security",
    blurb: "Re-verifies the safety claims on the shipped file: locked-down CSP, zero off-page requests, no network or storage APIs in page script, forms that cannot exfiltrate, and no credential-shaped text in any workspace file." },
  { kind: "seo", icon: "globe", label: "SEO",
    blurb: "Reads the document the way a crawler does: title and description length, a single H1, heading order, viewport, social cards, structured data and keyword coverage." },
  { kind: "accessibility", icon: "eye", label: "Accessibility",
    blurb: "Structural WCAG checks, plus the Critic’s real Chromium measurements for contrast, tap targets and readable text on a phone - never a second estimate of the same property." },
  { kind: "performance", icon: "chart", label: "Performance",
    blurb: "Counts what a phone has to carry: page and workspace weight, request count, DOM size and depth, repaint-heavy animation, image layout shift and measured 375px overflow." },
  { kind: "dependency", icon: "workflow", label: "Dependencies",
    blurb: "Inspects the deliverable and this service’s own manifests: pinned versions, imports nobody declared, drift between manifest and installed packages, unused dependencies. Advisory scanning is left to pip-audit and npm audit, and says so." },
  { kind: "tests", icon: "check", label: "Regression tests",
    blurb: "Writes a standard-library Python suite from the page that is live, runs it in a throwaway directory, and reports every case that no longer holds." },
];
export const auditOf = (kind) => AUDITS.find((a) => a.kind === kind) || {};

/** The build pipeline, exactly as app/orchestrator/graph.py runs it. */
export const PIPELINE = [
  { agent: "researcher", icon: "search", label: "Researcher", output: "brief",
    does: "Reads the idea as a market: who the page is for, what they already use, what would make them act." },
  { agent: "strategist", icon: "target", label: "Strategist", output: "strategy",
    does: "Chooses the positioning and the section order the page will argue with." },
  { agent: "copywriter", icon: "chat", label: "Copywriter", output: "content",
    does: "Writes the headline, body copy, feature blocks, FAQ and calls to action." },
  { agent: "designer", icon: "sparkle", label: "Designer", output: "design",
    does: "Turns the strategy into a design brief - palette, type, spacing, hero shape - within this run's seeded style direction." },
  { agent: "engineer", icon: "code", label: "Engineer", output: "html",
    does: "Publishes the page as a file set (index.html plus the derived styles.css / app.js) through the sanitizer." },
  { agent: "critic", icon: "shield", label: "Critic", output: "check_results",
    does: "Drives real Chromium at 1280px and 375px, measures the page, and writes fix instructions for the owning agent." },
  { agent: "panel", icon: "user", label: "Audience panel", output: "panel",
    does: "Simulated readers react to the page. A bonus, never a gate - a failure here cannot sink a run." },
  { agent: "system", icon: "check", label: "Readiness + approval", output: "readiness",
    does: "Scores the build, then stops at awaiting_approval. Nothing deploys until you approve." },
  { agent: "rocket", icon: "rocket", label: "Launcher", output: "deploy_url",
    does: "Only runs after approval: publishes the page and drafts the launch kit." },
];