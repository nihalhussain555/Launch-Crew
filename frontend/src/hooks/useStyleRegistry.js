import { useEffect, useState } from "react";
import { api } from "../api";

/**
 * The backend design registry, loaded once per mount.
 *
 * Pages that only want to name a style treat `reg === null` as "still loading" and say so rather than
 * guessing a label from the template card - the registry is the only source for a style's display name.
 */
export function useStyleRegistry() {
  const [reg, setReg] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let dead = false;
    api.styles()
      .then((r) => { if (!dead) setReg(r); })
      .catch((e) => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, []);
  const styleOf = (key) => (reg?.styles || []).find((s) => s.key === key) || null;
  return { reg, error, styleOf };
}
