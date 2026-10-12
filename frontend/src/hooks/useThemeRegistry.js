import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

/**
 * The backend theme registry, loaded once per mount: the families, pairings, presets, colour slots,
 * scale limits and defaults the customizer draws itself from.
 *
 * `controls` is the shape the server stores (family, mode, colours, pairing, scale, density, width,
 * radius, shadow, button, card) — never a resolved theme, because derived values are recomputed on every
 * read so a later AA fix or new preset reaches a theme saved before it.
 */
export function useThemeRegistry() {
  const [reg, setReg] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    setReg(null);
    api.themeRegistry().then(setReg).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  return { reg, error, reload: load };
}

/** A starting control set: exactly what `resolve({})` stores, so a new theme begins where the API begins. */
export const blankTheme = (reg) => ({ ...(reg?.default || {}) });
