"""Launch Readiness Score (0-100): a transparent blend of measurable signals. Pure function, no LLM.

  Page quality      50 pts  real-browser checks (errors -12 each, warnings -3 each)
  Audience reaction 30 pts  average score from the simulated audience panel (optional)
  Safety & hygiene  20 pts  -5 per unsafe element the sanitizer had to strip
  Crew audits       20 pts  average score of the on-demand audits taken against this exact build

Components that cannot be measured (e.g. panel skipped) are left out and the total is re-normalised.
"""


def compute_readiness(state) -> dict:
    comps = []
    if state.check_results:
        cs = state.check_summary or {}
        err, warn = cs.get("errors", 0), cs.get("warnings", 0)
        comps.append({"id": "quality", "label": "Page quality", "score": max(0, 50 - 12 * err - 3 * warn), "max": 50,
                      "detail": "All browser checks passed" if not (err or warn) else f"{err} error(s), {warn} warning(s) in browser checks"})
    if state.panel:
        avg, n = state.panel.get("avg_score", 0), len(state.panel.get("reactions", []))
        comps.append({"id": "audience", "label": "Audience reaction", "score": round(avg / 10 * 30), "max": 30,
                      "detail": f"{avg}/10 average; {state.panel.get('signups', 0)} of {n} simulated visitors would sign up"})
    v = len(state.sanitizer_violations or [])
    comps.append({"id": "hygiene", "label": "Safety & hygiene", "score": max(0, 20 - 5 * v), "max": 20,
                  "detail": "No unsafe elements had to be removed" if not v else f"{v} unsafe element(s) were stripped from the page"})
    # Only reports taken against the build that is live now count; an older page's findings are stale.
    fresh = [r for r in (getattr(state, "audits", None) or {}).values()
             if r.get("version") == state.html_version and r.get("score") is not None]
    if fresh:
        avg = sum(r["score"] for r in fresh) / len(fresh)
        named = ", ".join(f"{r['kind']} {r['score']}" for r in sorted(fresh, key=lambda r: r.get("kind", "")))
        comps.append({"id": "audits", "label": "Crew audits", "score": round(avg / 100 * 20), "max": 20,
                      "detail": f"{len(fresh)} audit(s) on v{state.html_version}: {named}"})
    total = round(sum(c["score"] for c in comps) / sum(c["max"] for c in comps) * 100)
    verdict = "Ready to launch" if total >= 85 else "Almost there" if total >= 65 else "Needs work"
    return {"total": total, "verdict": verdict, "components": comps}