const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001').replace(/\/$/, '');

async function request(path, options = {}) {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  const response = await fetch(url, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });

  const contentType = response.headers.get('content-type') || '';
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const details = typeof payload === 'string' ? payload : payload?.detail || payload?.message || 'Request failed';
    throw new Error(typeof details === 'string' ? details : JSON.stringify(details));
  }

  return payload;
}

export const api = {
  health: () => request('/health'),
  getMe: () => request('/api/me'),
  githubLogin: () => {
    window.location.href = `${API_BASE}/api/auth/github/login`;
  },
  logout: () =>
    request('/api/auth/logout', {
      method: 'POST',
    }),
  listGithubRepos: () => request('/api/github/repos'),
  importRepository: (payload) =>
    request('/api/repos/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getRepo: (repoId) => request(`/api/repos/${encodeURIComponent(repoId)}`),
  getRepoStatus: (repoId) => request(`/api/repos/${encodeURIComponent(repoId)}/status`),
  getRepoTree: (repoId) => request(`/api/repos/${encodeURIComponent(repoId)}/tree`),
  getFileContent: (repoId, filePath) => request(`/api/repos/${encodeURIComponent(repoId)}/file?path=${encodeURIComponent(filePath)}`),
  searchRepo: (repoId, query) => request(`/api/repos/${encodeURIComponent(repoId)}/search?q=${encodeURIComponent(query)}`),
  connectRepo: (payload) =>
    request('/repos/connect', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  askQuestion: (payload) =>
    request('/query', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  askQuestionStream: async (payload, { onStart, onToken, onComplete, onError } = {}) => {
    const url = `${API_BASE}/query/stream`;
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errText = await response.text();
      let msg = 'Request failed';
      try {
        const parsed = JSON.parse(errText);
        msg = parsed.detail || parsed.message || errText;
      } catch {
        msg = errText || `HTTP ${response.status}`;
      }
      throw new Error(msg);
    }

    if (!response.body) {
      throw new Error('ReadableStream not supported.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      let currentEvent = 'message';
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) {
          currentEvent = 'message';
          continue;
        }
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim();
          try {
            const data = JSON.parse(dataStr);
            if (currentEvent === 'start') {
              onStart?.(data);
            } else if (currentEvent === 'token') {
              onToken?.(data.text || '');
            } else if (currentEvent === 'complete') {
              onComplete?.(data);
            } else if (currentEvent === 'error') {
              onError?.(new Error(data.message || 'Stream error occurred'));
            }
          } catch (e) {
            console.error('Failed to parse SSE payload:', dataStr, e);
          }
        }
      }
    }
  },
  resetConversation: (repoId) =>
    request(`/api/repos/${encodeURIComponent(repoId)}/conversation/reset`, {
      method: 'POST',
    }),
  getGraph: (repoId, functionName) =>
    request(`/graph/${encodeURIComponent(repoId)}/${encodeURIComponent(functionName)}`),
};
