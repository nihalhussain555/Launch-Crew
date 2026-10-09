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
const del = async (path) => { await raw(path, { method: "DELETE" }); };

export const api = {
  register: (b) => post("/api/auth/register", b),
  login: (b) => post("/api/auth/login", b),
  me: () => json("/api/auth/me"),
  stats: () => json("/api/stats"),
  listProjects: () => json("/api/projects"),
  createProject: (idea) => post("/api/projects", { idea }),
  getProject: (id) => json(`/api/projects/${id}`),
  deleteProject: (id) => del(`/api/projects/${id}`),
  createRun: (projectId) => post(`/api/projects/${projectId}/runs`),
  getRun: (id) => json(`/api/runs/${id}`),
  approve: (id) => post(`/api/runs/${id}/approve`),
  revise: (id, instruction, target) => post(`/api/runs/${id}/revise`, { instruction, target }),
  getHtml: async (id) => (await raw(`/api/runs/${id}/html`)).text(),
  screenshotUrl: async (id, vp) => URL.createObjectURL(await (await raw(`/api/runs/${id}/screenshots/${vp}`)).blob()),
  share: (id) => post(`/api/runs/${id}/share`),
  unshare: (id) => del(`/api/runs/${id}/share`),
  feedback: (id) => json(`/api/runs/${id}/feedback`),
  applyFeedback: (id, ids, target) => post(`/api/runs/${id}/feedback/apply`, { ids, target }),
  // workspace: generated files, version history, diffs and AI actions
  files: (id) => json(`/api/runs/${id}/files`),
  fileText: async (id, name) => (await raw(`/api/runs/${id}/files/${encodeURIComponent(name)}`)).text(),
  filesZip: async (id) => URL.createObjectURL(await (await raw(`/api/runs/${id}/files.zip`)).blob()),
  versions: (id) => json(`/api/runs/${id}/versions`),
  versionHtml: async (id, v) => (await raw(`/api/runs/${id}/versions/${v}/html`)).text(),
  diff: (id, from, to) => json(`/api/runs/${id}/diff?from=${from}&to=${to}`),
  chat: (id, text) => post(`/api/runs/${id}/chat`, { text }),
  debug: (id) => post(`/api/runs/${id}/debug`),
  restore: (id, version) => post(`/api/runs/${id}/restore`, { version }),
  // crew audits: deterministic scans of the live page, plus the repair loop that applies their findings
  audit: (id, agents) => post(`/api/runs/${id}/audit`, agents ? { agents } : {}),
  auditRepair: (id, agents) => post(`/api/runs/${id}/audit/repair`, agents ? { agents } : {}),
  tests: (id) => json(`/api/runs/${id}/tests`),
  testsFile: async (id) => (await raw(`/api/runs/${id}/tests/file`)).text(),
  // environment manager (metadata only: the server never sends a secret value)
  configStatus: () => json("/api/config/status"),
  envExample: () => json("/api/config/env-example"),
  // public (no login): shareable preview + feedback
  publicInfo: (token) => json(`/api/public/${token}`),
  publicHtml: async (token) => (await raw(`/api/public/${token}/html`)).text(),
  publicFeedback: (token, body) => post(`/api/public/${token}/feedback`, body),
  // EventSource can't send headers, so the stream endpoint accepts ?token= (that endpoint only)
  streamUrl: (id) => `${API_URL}/api/runs/${id}/stream?token=${encodeURIComponent(getToken() || "")}`,
};