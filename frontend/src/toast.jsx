import { createContext, useCallback, useContext, useRef, useState } from "react";
import Icon from "./components/Icon";

const Ctx = createContext(() => {});
export const useToast = () => useContext(Ctx);

const KIND = {
  success: { icon: "check", title: "Success" },
  error: { icon: "close", title: "Something went wrong" },
  warning: { icon: "alert", title: "Heads up" },
  info: { icon: "sparkle", title: "FYI" },
  loading: { icon: "refresh", title: "Working…" },
};
const DURATION = { success: 4000, error: 6000, warning: 5000, info: 4500 };

/**
 * toast(message, type)  — type: success | error | warning | info | loading
 * "loading" stays on screen until it is dismissed or replaced.
 */
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const id = useRef(0);
  const dismiss = useCallback((i) => setItems((p) => p.filter((t) => t.id !== i)), []);
  const push = useCallback((message, type = "info") => {
    const kind = KIND[type] ? type : "info";
    const i = ++id.current;
    setItems((p) => [...p.slice(-3), { id: i, message, kind }]);
    const ms = DURATION[kind];
    if (ms) setTimeout(() => dismiss(i), ms);
    return i;
  }, [dismiss]);

  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="toast-wrap" role="status" aria-live="polite">
        {items.map((t) => {
          const k = KIND[t.kind];
          return (
            <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : undefined}>
              <span className="t-ico"><Icon name={k.icon} size={17} className={t.kind === "loading" ? "spin" : ""} /></span>
              <div className="t-body">
                <span className="t-title">{k.title}</span>
                <span className="t-msg">{t.message}</span>
              </div>
              <button className="icon-btn" onClick={() => dismiss(t.id)} aria-label="Dismiss notification"><Icon name="close" size={14} /></button>
              {DURATION[t.kind] && <i className="t-bar" style={{ animationDuration: `${DURATION[t.kind]}ms` }} />}
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}
