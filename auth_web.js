(function () {
  const API_URL_KEY = 'homewash.apiUrl';
  const SESSION_KEY = 'homewash.authSession';
  const USER_KEY = 'homewash.authUser';
  const KNOWN_CLIENTS_KEY = 'homewash.knownClients';
  const PROTECTED_PAGES = new Set(['dashboard.html', 'agendamentos.html', 'sync.html']);
  const DEFAULT_USER = {
    login: 'operacao-local',
    nome: 'Sessao nao iniciada',
    email: '',
    is_admin: false,
  };

  function normalizeBaseUrl(url) {
    const clean = String(url || '').trim().replace(/\/$/, '');
    if (!clean) return '';
    if (/^https?:\/\//.test(clean)) return clean;
    return `https://${clean}`;
  }

  function normalizeFetchError(error, fallbackMessage) {
    const message = String((error && error.message) || '').trim();
    if (!message) {
      return new Error(fallbackMessage);
    }
    if (/Failed to fetch|NetworkError|Load failed/i.test(message)) {
      return new Error('Falha ao conectar com a API. Verifique a URL configurada e se o tunnel da API ainda esta ativo.');
    }
    return new Error(message);
  }

  function getApiUrlFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const queryValue = params.get('api') || params.get('apiUrl') || params.get('api_url') || '';
    return normalizeBaseUrl(queryValue);
  }

  function getConfiguredApiUrl() {
    const queryApiUrl = getApiUrlFromQuery();
    if (queryApiUrl) {
      localStorage.setItem(API_URL_KEY, queryApiUrl);
      return queryApiUrl;
    }
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

  function getStoredSession() {
    const raw = localStorage.getItem(SESSION_KEY) || '';
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object') return null;
      return parsed;
    } catch (error) {
      return null;
    }
  }

  function getToken() {
    const session = getStoredSession();
    return String((session && session.token) || '').trim();
  }

  function isSessionExpired(session) {
    const expiresAt = String((session && session.expires_at) || '').trim();
    if (!expiresAt) return true;
    const timestamp = Date.parse(expiresAt);
    if (Number.isNaN(timestamp)) return true;
    return timestamp <= Date.now();
  }

  function hasValidSession() {
    const session = getStoredSession();
    return Boolean(session && session.token && !isSessionExpired(session));
  }

  function getStoredUser() {
    const session = getStoredSession();
    if (session && session.user) {
      return { ...DEFAULT_USER, ...session.user };
    }
    const raw = localStorage.getItem(USER_KEY) || '';
    if (!raw) return { ...DEFAULT_USER };
    try {
      return { ...DEFAULT_USER, ...JSON.parse(raw) };
    } catch (error) {
      return { ...DEFAULT_USER };
    }
  }

  function setSession(data) {
    const session = {
      token: String((data && data.token) || '').trim(),
      expires_at: String((data && data.expires_at) || '').trim(),
      user: { ...DEFAULT_USER, ...((data && data.user) || {}) },
    };
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    localStorage.setItem(USER_KEY, JSON.stringify(session.user));
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
    localStorage.setItem(USER_KEY, JSON.stringify(DEFAULT_USER));
  }

  function getCurrentPage() {
    const path = String(window.location.pathname || '').split('/').pop();
    return path || 'index.html';
  }

  function isProtectedPage() {
    return PROTECTED_PAGES.has(getCurrentPage());
  }

  function buildLoginUrl(nextPage) {
    const next = String(nextPage || `${getCurrentPage()}${window.location.search || ''}`).trim();
    if (!next || next === 'login.html') return 'login.html';
    return `login.html?next=${encodeURIComponent(next)}`;
  }

  function redirectToLogin(nextPage) {
    window.location.href = buildLoginUrl(nextPage);
  }

  function readArray(key) {
    try {
      const raw = localStorage.getItem(key) || '[]';
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function writeArray(key, items) {
    localStorage.setItem(key, JSON.stringify(Array.isArray(items) ? items : []));
  }

  function normalizeClientName(name) {
    return String(name || '').trim();
  }

  function rememberClientName(name) {
    const normalized = normalizeClientName(name);
    if (!normalized) return;
    const current = new Set(readArray(KNOWN_CLIENTS_KEY).map((item) => normalizeClientName(item)).filter(Boolean));
    current.add(normalized);
    writeArray(KNOWN_CLIENTS_KEY, Array.from(current).sort((left, right) => left.localeCompare(right, 'pt-BR')));
  }

  function rememberClientList(items) {
    (Array.isArray(items) ? items : []).forEach((item) => {
      if (!item || typeof item !== 'object') return;
      rememberClientName(item.nome || item.cliente || item.payload?.nome || item.payload?.cliente || '');
    });
  }

  function listKnownClients() {
    const names = new Set(readArray(KNOWN_CLIENTS_KEY).map((item) => normalizeClientName(item)).filter(Boolean));
    readArray('homewash.pendingClients').forEach((item) => names.add(normalizeClientName(item && item.payload && item.payload.nome)));
    readArray('homewash.pendingSchedules').forEach((item) => names.add(normalizeClientName(item && item.payload && item.payload.cliente)));
    readArray('homewash.pendingQuotes').forEach((item) => names.add(normalizeClientName(item && item.payload && item.payload.cliente)));
    return Array.from(names).filter(Boolean).sort((left, right) => left.localeCompare(right, 'pt-BR'));
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

    let response;
    try {
      response = await fetch(`${base}${path}`, { ...options, headers });
    } catch (error) {
      throw normalizeFetchError(error, 'Falha ao conectar com a API.');
    }
    const payload = await response.json().catch(() => ({}));

    if (response.status === 401) {
      clearSession();
      if (isProtectedPage()) {
        redirectToLogin();
      }
    }

    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || 'Falha ao falar com a API.');
    }

    return payload;
  }

  async function requireAuth(options = {}) {
    const settings = { redirectOnFail: true, ...(options || {}) };
    if (!hasValidSession()) {
      clearSession();
      if (settings.redirectOnFail) {
        redirectToLogin();
      }
      throw new Error('Faca login para continuar.');
    }

    const session = getStoredSession();
    try {
      const payload = await apiFetch('/api/auth/me');
      const nextSession = {
        token: session.token,
        expires_at: payload.data && payload.data.expires_at ? payload.data.expires_at : session.expires_at,
        user: payload.data && payload.data.user ? payload.data.user : session.user,
      };
      setSession(nextSession);
      return nextSession;
    } catch (error) {
      clearSession();
      if (settings.redirectOnFail) {
        redirectToLogin();
      }
      throw error;
    }
  }

  async function login(usuario, senha) {
    const base = getApiBase();
    if (!base) {
      throw new Error('Informe a URL da API antes de fazer login.');
    }

    let response;
    try {
      response = await fetch(`${base}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ usuario, senha }),
      });
    } catch (error) {
      throw normalizeFetchError(error, 'Falha ao fazer login.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || 'Falha ao fazer login.');
    }
    setSession(data);
    return data;
  }

  async function register(payload) {
    const base = getApiBase();
    if (!base) {
      throw new Error('Informe a URL da API antes de criar o acesso.');
    }

    let response;
    try {
      response = await fetch(`${base}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {}),
      });
    } catch (error) {
      throw normalizeFetchError(error, 'Falha ao criar o acesso.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || 'Falha ao criar o acesso.');
    }
    setSession(data);
    return data;
  }

  async function logout() {
    const base = getApiBase();
    const token = getToken();
    if (base && token) {
      try {
        await fetch(`${base}/api/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
        });
      } catch (error) {
      }
    }
    clearSession();
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

  if (isProtectedPage()) {
    requireAuth().catch(() => {});
  }

  window.HomeWashAuth = {
    apiFetch,
    bindApiInput,
    buildLoginUrl,
    clearSession,
    getApiBase,
    getNextPage,
    getStoredUser,
    getToken,
    hasValidSession,
    isProtectedPage,
    login,
    listKnownClients,
    logout,
    normalizeBaseUrl,
    register,
    rememberClientList,
    rememberClientName,
    requireAuth,
    saveApiInput,
    setApiBase,
  };
})();