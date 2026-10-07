import { createContext, useCallback, useContext, useEffect, useState } from "react";

const KEY = "lc_theme"; // "system" | "light" | "dark"
const Ctx = createContext({ theme: "system", setTheme: () => {}, cycle: () => {} });
export const useTheme = () => useContext(Ctx);

const apply = (t) => {
  const dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
};

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => localStorage.getItem(KEY) || "system");

  useEffect(() => {
    apply(theme);
    localStorage.setItem(KEY, theme);
    if (theme !== "system") return undefined;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => apply("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [theme]);

  const cycle = useCallback(() => setTheme((t) => (t === "system" ? "light" : t === "light" ? "dark" : "system")), []);
  return <Ctx.Provider value={{ theme, setTheme, cycle }}>{children}</Ctx.Provider>;
}