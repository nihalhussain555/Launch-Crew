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
const patch = (path, body) => json(path, { method: "PATCH", body: JSON.stringify(body) });
const put = (path, body) => json(path, { method: "PUT", body: JSON.stringify(body) });
const del = async (path) => { await raw(path, { method: "DELETE" }); };

export const api = {
  register: (b) => post("/api/auth/register", b),
  login: (b) => post("/api/auth/login", b),
  me: () => json("/api/auth/me"),
  forgotPassword: (email) => post("/api/auth/forgot-password", { email }),
  resetPassword: (token, password) => post("/api/auth/reset-password", { token, password }),
  stats: () => json("/api/stats"),
  listProjects: () => json("/api/projects"),
  createProject: (idea, spec = {}, name = "") => post("/api/projects", { idea, name, spec }),
  getProject: (id) => json(`/api/projects/${id}`),
  deleteProject: (id) => del(`/api/projects/${id}`),
  createRun: (projectId, body) => post(`/api/projects/${projectId}/runs`, body),
  getRun: (id) => json(`/api/runs/${id}`),
  approve: (id) => post(`/api/runs/${id}/approve`),
  // Stop the build: ends the pipeline at its next agent boundary and keeps whatever it already published.
  stopRun: (id) => post(`/api/runs/${id}/stop`),
  revise: (id, instruction, target) => post(`/api/runs/${id}/revise`, { instruction, target }),
  getHtml: async (id) => (await raw(`/api/runs/${id}/html`)).text(),
  screenshotUrl: async (id, vp) => URL.createObjectURL(await (await raw(`/api/runs/${id}/screenshots/${vp}`)).blob()),
  share: (id) => post(`/api/runs/${id}/share`),
  unshare: (id) => del(`/api/runs/${id}/share`),
  feedback: (id) => json(`/api/runs/${id}/feedback`),
  applyFeedback: (id, ids, target) => post(`/api/runs/${id}/feedback/apply`, { ids, target }),
  // design registry: the styles and business types the creation wizard offers, straight from the backend
  styles: () => json("/api/styles"),
  styleDetail: (key) => json(`/api/styles/${encodeURIComponent(key)}`),
  resolveBrief: (spec) => post("/api/styles/resolve", spec),
  compareStyles: (projectId, styles) => post(`/api/projects/${projectId}/compare`, { styles }),
  // template gallery: the professional briefs the registry can actually build, and the page each composes to
  templates: () => json("/api/templates"),
  templateSections: () => json("/api/templates/sections"),
  templateDetail: (key) => json(`/api/templates/${encodeURIComponent(key)}`),
  templatePreview: (key) => json(`/api/templates/${encodeURIComponent(key)}/preview`),
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
  // workspace intelligence: index, impact, planned file-level patches and whole-file-set snapshots
  wsOverview: (id) => json(`/api/runs/${id}/workspace`),
  wsIndex: (id, full) => json(`/api/runs/${id}/workspace/index${full ? "?full=true" : ""}`),
  wsImpact: (id, text) => json(`/api/runs/${id}/workspace/impact?text=${encodeURIComponent(text)}`),
  wsPlan: (id, body) => post(`/api/runs/${id}/workspace/plan`, body),
  wsApply: (id, body) => post(`/api/runs/${id}/workspace/apply`, body),
  wsVersions: (id) => json(`/api/runs/${id}/workspace/versions`),
  wsVersion: (id, w) => json(`/api/runs/${id}/workspace/versions/${w}`),
  wsVersionFile: async (id, w, name) => (await raw(`/api/runs/${id}/workspace/versions/${w}/files/${encodeURIComponent(name)}`)).text(),
  wsDiff: (id, w, to) => json(`/api/runs/${id}/workspace/diff?w=${w}${to ? `&to=${to}` : ""}`),
  wsRestore: (id, w, baseVersion) => post(`/api/runs/${id}/workspace/restore`, { w, base_version: baseVersion }),
  wsCheckpoint: (id, label, note) => post(`/api/runs/${id}/workspace/checkpoint`, { label, note }),
  wsLabel: (id, w, label) => post(`/api/runs/${id}/workspace/versions/${w}/label`, { label }),
  wsUndo: (id, baseVersion) => post(`/api/runs/${id}/workspace/undo`, { base_version: baseVersion }),
  wsRedo: (id, baseVersion) => post(`/api/runs/${id}/workspace/redo`, { base_version: baseVersion }),
  // IDE: the same workspace as an editor. Files open with the digest a save must send back, source files
  // write directly, and the page's own names are refused here and go through wsPlan/wsApply instead.
  ideProjects: () => json("/api/ide/projects"),
  ideImportStatus: () => json("/api/ide/import"),
  ideFile: (id, name) => json(`/api/runs/${id}/workspace/files/${encodeURIComponent(name)}`),
  ideCreate: (id, body) => post(`/api/runs/${id}/workspace/files`, body),
  ideSave: (id, name, body) => put(`/api/runs/${id}/workspace/files/${encodeURIComponent(name)}`, body),
  ideRename: (id, name, to) => patch(`/api/runs/${id}/workspace/files/${encodeURIComponent(name)}`, { name: to }),
  ideDelete: (id, name) => json(`/api/runs/${id}/workspace/files/${encodeURIComponent(name)}`, { method: "DELETE" }),
  ideSearch: (id, { q, file = "", regex = false, caseSensitive = false }) => {
    const p = new URLSearchParams({ q });
    if (file) p.set("file", file);
    if (regex) p.set("regex", "true");
    if (caseSensitive) p.set("case", "true");
    return json(`/api/runs/${id}/workspace/search?${p}`);
  },
  // what this deployment can run: never a simulated terminal, always the real capability verdict
  ideExec: (id) => json(`/api/runs/${id}/workspace/exec`),
  ideRun: (id, body) => post(`/api/runs/${id}/workspace/exec`, body),
  // the assistant: plan in plain English, review the diff it proposes, then apply through the patch path
  ideAssistantPlan: (id, body) => post(`/api/runs/${id}/ide/plan`, body),
  ideAssistantProposals: (id) => json(`/api/runs/${id}/ide/proposals`),
  ideAssistantApply: (id, body) => post(`/api/runs/${id}/ide/apply`, body),
  ideAssistantReject: (id, body) => post(`/api/runs/${id}/ide/reject`, body),
  // preview lifecycle: read status, hand out one expiring sandboxed link, revoke every link again
  previewStatus: (id) => json(`/api/runs/${id}/preview`),
  previewStart: (id) => post(`/api/runs/${id}/preview`, {}),
  previewStop: (id) => json(`/api/runs/${id}/preview`, { method: "DELETE" }),
  // visual editor: map the element the preview frame reported, propose one patch for it, then decide
  visualLocate: (id, element) => post(`/api/runs/${id}/visual/locate`, { element }),
  visualPlan: (id, body) => post(`/api/runs/${id}/visual/plan`, body),
  visualProposals: (id) => json(`/api/runs/${id}/visual/proposals`),
  visualApply: (id, body) => post(`/api/runs/${id}/visual/apply`, body),
  visualReject: (id, body) => post(`/api/runs/${id}/visual/reject`, body),
  // design system: the customizer's own data source and the user's saved theme library
  themeRegistry: () => json("/api/themes/registry"),
  themePreviewPage: (theme, style) => post("/api/themes/preview-page", { theme, style: style || "" }),
  listThemes: () => json("/api/themes"),
  saveTheme: (name, theme) => post("/api/themes", { name, theme }),
  getTheme: (id) => json(`/api/themes/${id}`),
  updateTheme: (id, body) => patch(`/api/themes/${id}`, body),
  duplicateTheme: (id) => post(`/api/themes/${id}/duplicate`),
  resetTheme: (id) => post(`/api/themes/${id}/reset`),
  restoreTheme: (id) => post(`/api/themes/${id}/restore`),
  deleteTheme: (id) => del(`/api/themes/${id}`),
  themeDirection: (id, style) => post(`/api/themes/${id}/direction`, { style: style || "" }),
  // a theme on a live run: what the tokens would rewrite, one reviewable patch, then apply or reject
  runTheme: (id) => json(`/api/runs/${id}/theme`),
  themeFromRequest: (id, body) => post(`/api/runs/${id}/theme/from-request`, body),
  themePreview: (id, body) => post(`/api/runs/${id}/theme/preview`, body),
  themePropose: (id, body) => post(`/api/runs/${id}/theme/propose`, body),
  themeApply: (id, body) => post(`/api/runs/${id}/theme/apply`, body),
  themeReject: (id, body) => post(`/api/runs/${id}/theme/reject`, body),
  // real features on a live run: the catalog, what a request means, one reviewable build, then apply or reject
  capabilities: () => json("/api/capabilities"),
  featureStatus: (id) => json(`/api/runs/${id}/features`),
  featurePlan: (id, body) => post(`/api/runs/${id}/features/plan`, body),
  featurePropose: (id, body) => post(`/api/runs/${id}/features/propose`, body),
  featureApply: (id, body) => post(`/api/runs/${id}/features/apply`, body),
  featureReject: (id, body) => post(`/api/runs/${id}/features/reject`, body),
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