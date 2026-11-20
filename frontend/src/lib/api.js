// All backend calls go through here. The backend URL comes from VITE_API_URL (set it in Vercel / .env).
// Without it: localhost:8000 when running locally, otherwise the deployed backend.
const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const DEFAULT_API = isLocal ? 'http://localhost:8000' : 'https://talentdesk-two.vercel.app';
export const API_BASE = (import.meta.env.VITE_API_URL || DEFAULT_API).replace(/\/+$/, '');

export const apiUrl = (path) => `${API_BASE}/${String(path).replace(/^\/+/, '')}`;

async function request(path, { method = 'GET', body, role, params, form } = {}) {
  const url = new URL(apiUrl(path));
  if (params) Object.entries(params).forEach(([k, v]) => v != null && v !== '' && url.searchParams.set(k, v));
  const headers = {};
  if (role) headers['X-User-Role'] = role;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const res = await fetch(url, { method, headers, body: payload });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const msg = data?.detail || data?.error || data?.response || `Request failed (${res.status})`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  login: (email, phone, role) => request('login', { method: 'POST', body: { email, phone, role } }),
  chat: (sessionId, message, role) =>
    request('chat', { method: 'POST', body: { session_id: sessionId, message, user_role: role } }),
  uploadResume: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('upload', { method: 'POST', form });
  },
  notifications: (role, email) => request('notifications', { params: { role, email } }),
  dashboard: () => request('admin/dashboard'),
  approveRequest: (id) => request(`admin/requests/${id}/approve`, { method: 'POST' }),
  deleteJob: (id) => request(`admin/jobs/${id}`, { method: 'DELETE' }),
  setCandidateStatus: (id, status) =>
    request(`admin/candidates/${id}/status`, { method: 'PUT', params: { status } }),
  kbDocuments: () => request('kb/documents'),
  kbUpload: (file, role) => {
    const form = new FormData();
    form.append('file', file);
    return request('kb/upload', { method: 'POST', form, role });
  },
  kbDelete: (id, role) => request(`kb/documents/${id}`, { method: 'DELETE', role }),
  kbSearch: (query) => request('kb/search', { method: 'POST', body: { query } }),
  kbReindexJobs: (role) => request('kb/reindex-jobs', { method: 'POST', role }),
};

export const exportUrl = (type) => apiUrl(`export?type=${encodeURIComponent(type)}`);

export const newSessionId = () =>
  (globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);
