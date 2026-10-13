import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

/**
 * The template gallery, read from `app/agents/templates.py` through GET /api/templates.
 *
 * Nothing about a template is kept on this side of the wire: the card's style, site type, content blocks
 * and feature statuses are the same fields the run composes its page from, so a gallery cannot advertise
 * a shape the builder does not have code for.
 */
export function useTemplates() {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    setCatalog(null);
    api.templates().then(setCatalog).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const list = catalog?.templates || [];
  const byKey = useCallback((key) => list.find((t) => t.key === key) || null, [list]);
  // The catalogue numbers the templates in registry order, which is the order the gallery reads in.
  const numberOf = useCallback((key) => {
    const i = list.findIndex((t) => t.key === key);
    return i < 0 ? "" : String(i + 1).padStart(2, "0");
  }, [list]);
  const inCategory = useCallback((cat) => list.filter((t) => t.category === cat), [list]);

  return { catalog, list, error, load, byKey, numberOf, inCategory };
}

/**
 * The wizard link a card hands over: only the template's key travels, because the brief itself is read
 * back from GET /api/templates/{key} - a query string of styles and sections would be a second copy of
 * the registry that the registry could change underneath.
 */
export const templateWizardLink = (t) => `/new?template=${encodeURIComponent(t.key)}`;

/** The catalog's three honest states, in the short words a card has room for. Never upgraded by a card. */
export const STATUS_TONE = { generated: "ok", scaffold: "", "needs-external-setup": "warn" };
export const STATUS_SHORT = { generated: "works in the page", scaffold: "source you start",
                              "needs-external-setup": "needs your keys" };
