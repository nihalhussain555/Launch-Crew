// API client: base URL from VITE_API_URL, JWT from localStorage.
export const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const KEY = "lc_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => (t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY));

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function raw(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, { ...opts, headers });
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }
  if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event("lc-logout")); }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d) => d.msg).join("; ") : msg;
    } catch { /* non-JSON error body */ }
    throw new ApiError(msg, res.status);
  }
  return res;
}
const json = async (path, opts) => (await raw(path, opts)).json();
const post = (path, body) => json(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  register: (b) => post("/api/auth/register", b),
  login: (b) => post("/api/auth/login", b),
  me: () => json("/api/auth/me"),
  listProjects: () => json("/api/projects"),
  createProject: (idea) => post("/api/projects", { idea }),
  getProject: (id) => json(`/api/projects/${id}`),
  createRun: (projectId) => post(`/api/projects/${projectId}/runs`),
  getRun: (id) => json(`/api/runs/${id}`),
  approve: (id) => post(`/api/runs/${id}/approve`),
  revise: (id, instruction, target) => post(`/api/runs/${id}/revise`, { instruction, target }),
  getHtml: async (id) => (await raw(`/api/runs/${id}/html`)).text(),
  screenshotUrl: async (id, vp) => URL.createObjectURL(await (await raw(`/api/runs/${id}/screenshots/${vp}`)).blob()),
  // EventSource can't send headers, so the stream endpoint accepts ?token= (that endpoint only)
  streamUrl: (id) => `${API_URL}/api/runs/${id}/stream?token=${encodeURIComponent(getToken() || "")}`,
};
