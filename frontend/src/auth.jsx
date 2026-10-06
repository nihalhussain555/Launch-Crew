import { createContext, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(!!getToken());

  useEffect(() => {
    if (getToken()) api.me().then(setUser).catch(() => setToken(null)).finally(() => setLoading(false));
    const out = () => setUser(null);
    window.addEventListener("lc-logout", out);
    return () => window.removeEventListener("lc-logout", out);
  }, []);

  const finish = (res) => { setToken(res.access_token); setUser(res.user); };
  const value = {
    user, loading,
    login: async (email, password) => finish(await api.login({ email, password })),
    register: async (email, password, name) => finish(await api.register({ email, password, name })),
    logout: () => { setToken(null); setUser(null); },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
