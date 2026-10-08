import { createContext, useCallback, useContext, useEffect, useState } from "react";

const KEY = "lc_theme"; // "light" | "dark"
const Ctx = createContext({ theme: "light", setTheme: () => {}, cycle: () => {} });
export const useTheme = () => useContext(Ctx);

// The device setting only seeds the very first visit; afterwards the choice is always explicit.
const read = () => {
  const saved = localStorage.getItem(KEY);
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(read);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(KEY, theme);
  }, [theme]);

  const cycle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return <Ctx.Provider value={{ theme, setTheme, cycle }}>{children}</Ctx.Provider>;
}
