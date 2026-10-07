// The API returns naive UTC timestamps (no "Z"); browsers would read them as local time. Normalise.
export const parseDate = (iso) => new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);

export const fmtDate = (iso) => (iso ? parseDate(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

export function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - parseDate(iso).getTime()) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const compact = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n ?? 0));

/** URL-safe id for a template title, e.g. "Inbox zero" → "inbox-zero". */
export const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");

/** Only same-origin app paths, so a crafted ?next= can never bounce the user offsite. */
export function safeNext(raw, fallback = "/dashboard") {
  if (!raw) return fallback;
  let next = raw;
  try { next = decodeURIComponent(raw); } catch { /* keep the raw value */ }
  return next.startsWith("/") && !next.startsWith("//") ? next : fallback;
}

/** Copy text to the clipboard. Falls back to execCommand when navigator.clipboard is unavailable (insecure origins). */
export async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the legacy path */ }
  try {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch { return false; }
}