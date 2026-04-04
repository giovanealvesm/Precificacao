(function () {
  const API_URL_KEY = 'homewash.apiUrl';
  const TOKEN_KEY = 'homewash.authToken';
  const USER_KEY = 'homewash.authUser';
  const EXPIRES_KEY = 'homewash.authExpiresAt';

  function normalizeBaseUrl(url) {
    const clean = String(url || '').trim().replace(/\/$/, '');
    if (!clean) return '';
    if (/^https?:\/\//.test(clean)) return clean;
    return `https://${clean}`;
  }

  function getConfiguredApiUrl() {
    const stored = localStorage.getItem(API_URL_KEY) || '';
    if (stored) return normalizeBaseUrl(stored);
    const config = window.HOME_WASH_CONFIG || {};
    if (typeof config.apiUrl === 'string' && config.apiUrl.trim()) {
      return normalizeBaseUrl(config.apiUrl);
    }
    return '';
  }

  function setApiBase(url) {
    const normalized = normalizeBaseUrl(url);
    if (normalized) {
      localStorage.setItem(API_URL_KEY, normalized);
    } else {
      localStorage.removeItem(API_URL_KEY);
    }
    return normalized;
  }

  function getApiBase() {
    return getConfiguredApiUrl();
  }

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || '';
  }

  function getStoredUser() {
    const raw = localStorage.getItem(USER_KEY) || '';
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (error) {
      return null;
    }
  }

  function setSession(data) {
    localStorage.setItem(TOKEN_KEY, data.token || '');
    localStorage.setItem(USER_KEY, JSON.stringify(data.user || {}));
    localStorage.setItem(EXPIRES_KEY, data.expires_at || '');
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem(EXPIRES_KEY);
  }

  async function apiFetch(path, options = {}) {
    const base = getApiBase();
    if (!base) {
      throw new Error('Informe a URL da API antes de continuar.');
    }

    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const token = getToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(`${base}${path}`, { ...options, headers });
    const payload = await response.json().catch(() => ({}));

    if (response.status === 401) {
      clearSession();
      const error = new Error(payload.error || 'Sessao invalida ou expirada.');
      error.code = 401;
      throw error;
    }

    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || 'Falha ao falar com a API.');
    }

    return payload;
  }

  function buildLoginUrl() {
    const current = window.location.pathname.split('/').pop() || 'dashboard.html';
    return `login.html?next=${encodeURIComponent(current)}`;
  }

  async function requireAuth() {
    if (!getToken()) {
      window.location.href = buildLoginUrl();
      throw new Error('Sessao nao encontrada.');
    }

    try {
      const payload = await apiFetch('/api/auth/me');
      if (payload && payload.data && payload.data.user) {
        localStorage.setItem(USER_KEY, JSON.stringify(payload.data.user));
      }
      return payload.data;
    } catch (error) {
      if (error.code === 401) {
        window.location.href = buildLoginUrl();
      }
      throw error;
    }
  }

  async function login(usuario, senha) {
    const payload = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ usuario, senha }),
    });
    setSession(payload.data || {});
    return payload.data;
  }

  async function logout() {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      if (error.code !== 401) {
        throw error;
      }
    } finally {
      clearSession();
    }
  }

  function bindApiInput(input) {
    if (!input) return;
    input.value = getApiBase();
  }

  function saveApiInput(input) {
    return setApiBase(input ? input.value : '');
  }

  function getNextPage(defaultPage = 'dashboard.html') {
    const params = new URLSearchParams(window.location.search);
    const next = String(params.get('next') || '').trim();
    if (!next || next === 'login.html') return defaultPage;
    return next;
  }

  window.HomeWashAuth = {
    apiFetch,
    bindApiInput,
    clearSession,
    getApiBase,
    getNextPage,
    getStoredUser,
    getToken,
    login,
    logout,
    normalizeBaseUrl,
    requireAuth,
    saveApiInput,
    setApiBase,
  };
})();