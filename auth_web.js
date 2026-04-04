(function () {
  const API_URL_KEY = 'homewash.apiUrl';
  const USER_KEY = 'homewash.authUser';
  const KNOWN_CLIENTS_KEY = 'homewash.knownClients';
  const DEFAULT_USER = {
    login: 'operacao-local',
    nome: 'Operacao Local',
    email: '',
    is_admin: true,
  };

  function normalizeBaseUrl(url) {
    const clean = String(url || '').trim().replace(/\/$/, '');
    if (!clean) return '';
    if (/^https?:\/\//.test(clean)) return clean;
    return `https://${clean}`;
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

  function getToken() {
    return '';
  }

  function getStoredUser() {
    const raw = localStorage.getItem(USER_KEY) || '';
    if (!raw) return { ...DEFAULT_USER };
    try {
      return { ...DEFAULT_USER, ...JSON.parse(raw) };
    } catch (error) {
      return { ...DEFAULT_USER };
    }
  }

  function setSession(data) {
    localStorage.setItem(USER_KEY, JSON.stringify({ ...DEFAULT_USER, ...(data.user || {}) }));
  }

  function clearSession() {
    localStorage.setItem(USER_KEY, JSON.stringify(DEFAULT_USER));
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

    const response = await fetch(`${base}${path}`, { ...options, headers });
    const payload = await response.json().catch(() => ({}));

    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || 'Falha ao falar com a API.');
    }

    return payload;
  }

  function buildLoginUrl() {
    return 'dashboard.html';
  }

  async function requireAuth() {
    const user = getStoredUser();
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    return { user, expires_at: '' };
  }

  async function login(usuario, senha) {
    const nome = String(usuario || '').trim() || DEFAULT_USER.nome;
    const data = { user: { ...DEFAULT_USER, login: nome.toLowerCase().replace(/\s+/g, '-'), nome } };
    setSession(data);
    return { ...data, expires_at: '' };
  }

  async function logout() {
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

  window.HomeWashAuth = {
    apiFetch,
    bindApiInput,
    clearSession,
    getApiBase,
    getNextPage,
    getStoredUser,
    getToken,
    login,
    listKnownClients,
    logout,
    normalizeBaseUrl,
    rememberClientList,
    rememberClientName,
    requireAuth,
    saveApiInput,
    setApiBase,
  };
})();