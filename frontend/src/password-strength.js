export const LABELS = ["Too short", "Weak", "Fair", "Strong", "Excellent"];

// Deterministic 0–4 score: length + character classes, no external lib.
export default function score(pw) {
  if (!pw) return 0;
  let s = 0;
  if (pw.length >= 8) s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(4, pw.length < 8 ? 1 : s);
}
