const TOKEN_KEY = 'stockgraph.session';
const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export const session = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (token) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export async function api(path, options = {}) {
  const headers = new Headers(options.headers);
  if (session.get()) headers.set('Authorization', `Bearer ${session.get()}`);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  let response;
  try {
    response = await fetch(`${base}/api/v1${path}`, {
      ...options, headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new Error('Cannot reach the Platform service. Check that it is running and try again.');
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : response.status >= 500
      ? 'The Platform service is unavailable. Please try again shortly.'
      : 'Please check your input and try again.';
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return data;
}

export const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const formatDate = (value) => value ? new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'Not available';
