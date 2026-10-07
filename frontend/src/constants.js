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