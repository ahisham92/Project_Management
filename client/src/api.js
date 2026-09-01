// Thin wrapper over fetch. The session lives in an httpOnly cookie, so requests
// only need credentials: 'include'.
async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'include',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  let payload = null;
  try { payload = await res.json(); } catch { /* empty body */ }

  if (!res.ok) {
    const error = new Error(payload?.error || `Request failed (${res.status})`);
    error.status = res.status;
    throw error;
  }
  return payload;
}

const qs = (params) => {
  const clean = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  return clean.length ? `?${new URLSearchParams(clean)}` : '';
};

export const api = {
  me: () => request('/auth/me'),
  login: (email, password) => request('/auth/login', { method: 'POST', body: { email, password } }),
  register: (email, name, password) => request('/auth/register', { method: 'POST', body: { email, name, password } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  changePassword: (current, next) => request('/auth/password', { method: 'POST', body: { current, next } }),

  portfolio: (params) => request(`/projects${qs(params)}`),
  createProject: (body) => request('/projects', { method: 'POST', body }),
  project: (id, params) => request(`/projects/${id}${qs(params)}`),
  updateProject: (id, body) => request(`/projects/${id}`, { method: 'PATCH', body }),
  deleteProject: (id) => request(`/projects/${id}`, { method: 'DELETE' }),

  sCurve: (id, params) => request(`/projects/${id}/s-curve${qs(params)}`),
  schedule: (id, params) => request(`/projects/${id}/schedule${qs(params)}`),
  budget: (id, params) => request(`/projects/${id}/budget${qs(params)}`),
  period: (id, params) => request(`/projects/${id}/period${qs(params)}`),

  createSection: (id, body) => request(`/projects/${id}/sections`, { method: 'POST', body }),
  updateSection: (id, sectionId, body) => request(`/projects/${id}/sections/${sectionId}`, { method: 'PATCH', body }),
  deleteSection: (id, sectionId) => request(`/projects/${id}/sections/${sectionId}`, { method: 'DELETE' }),

  trades: (id) => request(`/projects/${id}/trades`),
  createTrade: (id, body) => request(`/projects/${id}/trades`, { method: 'POST', body }),
  updateTrade: (id, tradeId, body) => request(`/projects/${id}/trades/${tradeId}`, { method: 'PATCH', body }),
  deleteTrade: (id, tradeId) => request(`/projects/${id}/trades/${tradeId}`, { method: 'DELETE' }),

  createTask: (id, body) => request(`/projects/${id}/tasks`, { method: 'POST', body }),
  task: (taskId) => request(`/tasks/${taskId}`),
  updateTask: (taskId, body) => request(`/tasks/${taskId}`, { method: 'PATCH', body }),
  deleteTask: (taskId) => request(`/tasks/${taskId}`, { method: 'DELETE' }),
  recordProgress: (taskId, body) => request(`/tasks/${taskId}/progress`, { method: 'POST', body }),

  timeEntries: (id, params) => request(`/projects/${id}/time-entries${qs(params)}`),
  addTimeEntry: (id, body) => request(`/projects/${id}/time-entries`, { method: 'POST', body }),
  deleteTimeEntry: (id, entryId) => request(`/projects/${id}/time-entries/${entryId}`, { method: 'DELETE' }),

  members: (id) => request(`/projects/${id}/members`),
  addMember: (id, body) => request(`/projects/${id}/members`, { method: 'POST', body }),
  removeMember: (id, userId) => request(`/projects/${id}/members/${userId}`, { method: 'DELETE' }),
};

export default api;
