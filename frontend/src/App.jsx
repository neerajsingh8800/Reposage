import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom';
import { api } from './lib/api';
import { ExplorerPanel } from './components/ExplorerPanel';
import { QueryComposer } from './components/QueryComposer';
import { AnswerPanel } from './components/AnswerPanel';
import { EngineeringContext } from './components/EngineeringContext';
import { SourceViewer } from './components/SourceViewer';
import { StatusBar } from './components/StatusBar';
import { VisualEnvironment } from './components/VisualEnvironment';

const suggestedQuestions = [
  'How does data flow through this repository?',
  'What are the core entry points?',
  'Where is configuration handled?',
  'What are the most important modules?',
  'How are the main components connected?',
];

const AuthContext = createContext(null);

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    api.getMe()
      .then((payload) => {
        if (isMounted) setUser(payload.user || null);
      })
      .catch(() => {
        if (isMounted) setUser(null);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return <AuthContext.Provider value={{ user, setUser, loading }}>{children}</AuthContext.Provider>;
}

function useAuth() {
  return useContext(AuthContext);
}

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="page-shell auth-page">
        <VisualEnvironment variant="auth" />
        <div className="app-loading-container">
          <div className="telemetry-loading-spinner" />
          <div className="app-loading">Verifying authentication credentials…</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function TopNavigation() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();

  async function handleLogout() {
    try {
      await api.logout();
    } catch (error) {
      console.error(error);
    }
    setUser(null);
    navigate('/', { replace: true });
  }

  return (
    <header className="top-nav">
      <div className="brand-wrap">
        <Link to={user ? '/repositories' : '/'} className="brand-mark">RepoSage</Link>
        <span className="brand-tagline">Living Codebase Atlas</span>
      </div>

      <nav className="topnav-links">
        <Link to="/repositories">Repositories</Link>
      </nav>

      {user ? (
        <div className="user-menu">
          <div className="user-badge">
            {user.avatar_url ? <img src={user.avatar_url} alt={user.login} /> : null}
            <span>{user.login || user.name}</span>
          </div>
          <button type="button" className="ghost-button small" onClick={handleLogout}>Logout</button>
        </div>
      ) : (
        <button type="button" className="primary-button small" onClick={() => api.githubLogin()}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 2 }}>
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
          </svg>
          Continue with GitHub
        </button>
      )}
    </header>
  );
}

function LandingPage() {
  const { user } = useAuth();
  const [authError, setAuthError] = useState('');

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const error = params.get('error');
    setAuthError(error || '');
    if (error) {
      window.history.replaceState({}, '', '/');
    }
  }, []);

  if (user) {
    return <Navigate to="/repositories" replace />;
  }

  return (
    <div className="page-shell auth-page">
      <VisualEnvironment variant="landing" />
      <TopNavigation />
      <main className="hero-panel">
        <div className="hero-copy">
          <div className="eyebrow">LIVING CODEBASE ATLAS</div>
          <h1>Understand the codebase. See what connects. Know what changes.</h1>
          <p>
            An immersive architectural studio for exploring complex repositories. Tracing dependency flows, mapping blast radius, and grounding answers with authoritative source citations.
          </p>
          {authError ? <div className="inline-error">{decodeURIComponent(authError)}</div> : null}
          <div className="hero-actions">
            <button type="button" className="primary-button" onClick={() => api.githubLogin()}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 4 }}>
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
              </svg>
              Continue with GitHub
            </button>
            <div className="account-switch-hint">
              Supports any GitHub account. To sign in with another account, sign out of github.com first or use a private window.
            </div>
          </div>
        </div>

        <div className="hero-card">
          <div className="hero-landscape-sketch" aria-hidden="true">
            <svg viewBox="0 0 400 160" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M10 140 C 90 110, 180 150, 260 100 C 320 60, 360 90, 390 70" stroke="rgba(94, 166, 133, 0.6)" strokeWidth="1.5" strokeDasharray="3 3"/>
              <path d="M10 110 C 80 80, 150 120, 240 70 C 310 30, 350 60, 390 40" stroke="rgba(217, 119, 87, 0.6)" strokeWidth="1.5"/>
              <path d="M10 80 C 100 50, 190 90, 280 40 C 330 20, 370 30, 390 15" stroke="rgba(97, 142, 168, 0.55)" strokeWidth="1.5" strokeDasharray="5 5"/>
              <circle cx="80" cy="80" r="4" fill="#5ea685" />
              <circle cx="240" cy="70" r="4" fill="#d97757" />
              <circle cx="310" cy="30" r="4" fill="#618ea8" />
              <line x1="80" y1="80" x2="240" y2="70" stroke="rgba(230, 225, 215, 0.35)" strokeWidth="1"/>
              <line x1="240" y1="70" x2="310" y2="30" stroke="rgba(230, 225, 215, 0.35)" strokeWidth="1"/>
              <text x="75" y="100" fill="#a6b0bd" fontSize="8" fontFamily="monospace">ARCH::ROOT</text>
              <text x="230" y="90" fill="#a6b0bd" fontSize="8" fontFamily="monospace">NODE::FLOW</text>
              <text x="300" y="50" fill="#a6b0bd" fontSize="8" fontFamily="monospace">CIT::EVID</text>
            </svg>
          </div>

          <div className="hero-tags-row">
            <span className="hero-tag accent">ARCHITECTURE</span>
            <span className="hero-tag terracotta">DEPENDENCIES</span>
            <span className="hero-tag amber">IMPACT</span>
            <span className="hero-tag">EVIDENCE</span>
          </div>

          <div className="mini-grid">
            <div className="mini-card">
              <span>Repositories</span>
              <strong>GitHub-backed</strong>
            </div>
            <div className="mini-card">
              <span>Indexing</span>
              <strong>Chunk + embed</strong>
            </div>
            <div className="mini-card">
              <span>Graph</span>
              <strong>Caller / callee</strong>
            </div>
            <div className="mini-card">
              <span>Answers</span>
              <strong>Cited evidence</strong>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

function AuthCallbackPage() {
  const navigate = useNavigate();
  const { setUser } = useAuth();

  useEffect(() => {
    let isMounted = true;

    api.getMe()
      .then((payload) => {
        if (!isMounted) return;
        setUser(payload.user || null);
        navigate('/repositories', { replace: true });
      })
      .catch(() => {
        if (!isMounted) return;
        setUser(null);
        navigate('/', { replace: true });
      });

    return () => {
      isMounted = false;
    };
  }, [navigate, setUser]);

  return (
    <div className="page-shell auth-page">
      <VisualEnvironment variant="auth" />
      <div className="app-loading-container">
        <div className="telemetry-loading-spinner" />
        <div className="app-loading">Establishing authenticated GitHub session…</div>
      </div>
    </div>
  );
}

function RepositorySelectionPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [repositories, setRepositories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [importing, setImporting] = useState('');
  const [filterQuery, setFilterQuery] = useState('');

  const userLogin = (user?.login || '').toLowerCase();
  const visibleRepositories = useMemo(() => {
    const rawList = (repositories || []).filter((repo) => {
      const name = (repo.name || '').trim().toLowerCase();
      const owner = (repo.owner || '').trim().toLowerCase();
      if (name && owner && name === owner) return false;
      if (name && userLogin && name === userLogin) return false;
      return true;
    });

    if (!filterQuery.trim()) return rawList;
    const q = filterQuery.trim().toLowerCase();
    return rawList.filter((r) =>
      (r.name || '').toLowerCase().includes(q) ||
      (r.owner || '').toLowerCase().includes(q) ||
      (r.description || '').toLowerCase().includes(q) ||
      (r.language || '').toLowerCase().includes(q)
    );
  }, [repositories, userLogin, filterQuery]);

  useEffect(() => {
    let isMounted = true;

    api.listGithubRepos()
      .then((payload) => {
        if (!isMounted) return;
        setRepositories(payload.repositories || []);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || 'Unable to load repositories.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  async function handleAnalyze(repo) {
    try {
      setImporting(repo.full_name);
      const repoId = repo.full_name ? repo.full_name.replace('/', '-') : (repo.name || 'repo');
      const result = await api.importRepository({
        repo_id: repoId,
        full_name: repo.full_name,
        clone_url: repo.clone_url,
        owner: repo.owner,
        name: repo.name,
      });
      if (!result || !result.repo_id) {
        throw new Error('Repository import response was empty.');
      }
      navigate(`/repositories/${encodeURIComponent(result.repo_id)}/prepare`);
    } catch (err) {
      setError(err.message || 'Repository analysis could not be started.');
    } finally {
      setImporting('');
    }
  }

  if (!user) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="page-shell repositories-page">
      <VisualEnvironment variant="repositories" />
      <TopNavigation />
      <main className="content-shell">
        <div className="section-header">
          <div>
            <div className="eyebrow">REPOSITORY OBSERVATORY</div>
            <h2>Choose a repository to analyze</h2>
          </div>

          <div className="repo-filter-box">
            <input
              type="text"
              className="repo-filter-input"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Filter repositories by name, language..."
            />
            {filterQuery ? (
              <button
                type="button"
                className="repo-filter-clear"
                onClick={() => setFilterQuery('')}
                title="Clear filter"
              >
                ✕
              </button>
            ) : null}
          </div>
        </div>

        {error ? (
          <div className="empty-panel" style={{ marginBottom: 18 }}>
            <div className="inline-error" style={{ marginBottom: 12 }}>{error}</div>
            <div style={{ display: 'flex', gap: 10 }}>
              <a href="/api/auth/github/login" className="primary-button small">
                Re-authenticate with GitHub
              </a>
              <button
                type="button"
                className="secondary-button small"
                onClick={() => {
                  setError('');
                  setLoading(true);
                  api.listGithubRepos()
                    .then((p) => setRepositories(p.repositories || []))
                    .catch((e) => setError(e.message || 'Unable to load repositories.'))
                    .finally(() => setLoading(false));
                }}
              >
                Retry
              </button>
            </div>
          </div>
        ) : null}

        {loading ? (
          <div className="empty-panel">
            <div className="telemetry-loading-spinner" />
            <div className="loading-state">Scanning accessible GitHub repositories…</div>
          </div>
        ) : visibleRepositories.length === 0 ? (
          <div className="empty-panel">
            <div className="empty-title">No repositories found</div>
            <div className="empty-copy">
              {filterQuery ? 'No repositories match your filter criteria.' : 'GitHub returned no repositories for the current account permissions.'}
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
              {filterQuery ? (
                <button
                  type="button"
                  className="secondary-button small"
                  onClick={() => setFilterQuery('')}
                >
                  Clear filter
                </button>
              ) : (
                <>
                  <a href="/api/auth/github/login" className="primary-button small">
                    Sign in with GitHub
                  </a>
                  <button
                    type="button"
                    className="secondary-button small"
                    onClick={() => {
                      setError('');
                      setLoading(true);
                      api.listGithubRepos()
                        .then((p) => setRepositories(p.repositories || []))
                        .catch((e) => setError(e.message || 'Unable to load repositories.'))
                        .finally(() => setLoading(false));
                    }}
                  >
                    Refresh
                  </button>
                </>
              )}
            </div>
          </div>
        ) : (
          <div className="repo-grid">
            {visibleRepositories.map((repo, idx) => (
              <article
                key={repo.full_name}
                className="repo-card animate-stagger"
                style={{ animationDelay: `${Math.min(idx * 50, 600)}ms` }}
              >
                <div className="repo-card-header">
                  <div className="repo-card-title-wrap">
                    <div className="repo-card-owner">{repo.owner}</div>
                    <h3 className="repo-card-title" title={repo.name}>{repo.name}</h3>
                  </div>
                  <span className={`visibility-badge ${repo.private ? 'private' : 'public'}`}>
                    {repo.private ? 'Private' : 'Public'}
                  </span>
                </div>

                <p className="repo-description">{repo.description || 'No description provided.'}</p>

                <div className="repo-meta-row compact">
                  <span className="meta-label">Language</span>
                  <span>{repo.language || 'Unknown'}</span>
                </div>
                <div className="repo-meta-row compact">
                  <span className="meta-label">Default branch</span>
                  <span>{repo.default_branch || 'main'}</span>
                </div>
                <div className="repo-meta-row compact">
                  <span className="meta-label">Updated</span>
                  <span>{repo.updated_at ? new Date(repo.updated_at).toLocaleDateString() : 'Unknown'}</span>
                </div>

                <button
                  type="button"
                  className="primary-button full-width analyze-cta-button"
                  onClick={() => handleAnalyze(repo)}
                  disabled={importing === repo.full_name}
                >
                  {importing === repo.full_name ? 'Preparing repository…' : 'Analyze Repository'}
                </button>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function RepositoryOverviewPage() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const [repo, setRepo] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isMounted = true;

    Promise.all([api.getRepo(repoId), api.getRepoStatus(repoId)])
      .then(([repoData, statusData]) => {
        if (!isMounted) return;
        setRepo(repoData);
        setStatus(statusData);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || 'Repository overview could not be loaded.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [repoId]);

  if (loading) {
    return (
      <div className="page-shell overview-page">
        <VisualEnvironment variant="overview" watermark={repoId} />
        <TopNavigation />
        <main className="content-shell">
          <div className="empty-panel">
            <div className="telemetry-loading-spinner" />
            <div className="loading-state">Compiling repository field report…</div>
          </div>
        </main>
      </div>
    );
  }

  if (error || !repo) {
    return (
      <div className="page-shell overview-page">
        <VisualEnvironment variant="overview" watermark={repoId} />
        <TopNavigation />
        <main className="content-shell">
          <div className="empty-panel">
            <div className="empty-title">Repository not ready</div>
            <div className="empty-copy">{error || 'This repository has not been indexed yet.'}</div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="page-shell overview-page">
      <VisualEnvironment variant="overview" watermark={repo.repo_name || repo.repo_id} />
      <TopNavigation />
      <main className="content-shell repo-overview">
        <div className="section-header">
          <div>
            <div className="eyebrow">FIELD REPORT</div>
            <h2>{repo.repo_name || repo.repo_id}</h2>
          </div>
          <div className="header-actions">
            <button type="button" className="secondary-button" onClick={() => navigate('/repositories')}>Back to Archive</button>
            <button type="button" className="primary-button" onClick={() => navigate(`/workspace/${repoId}`)}>Open RepoSage Workspace</button>
          </div>
        </div>

        <div className="overview-grid">
          <section className="panel-section report-card animate-stagger" style={{ animationDelay: '50ms' }}>
            <div className="section-label">REPOSITORY SPECIFICATION</div>
            <div className="repo-name">{repo.full_name || repo.repo_name}</div>
            <p className="repo-description" style={{ minHeight: 'auto', marginBottom: 14 }}>{repo.description || 'No repository description available.'}</p>
            <div className="repo-meta-row compact">
              <span className="meta-label">Owner</span>
              <span>{repo.owner || 'unknown'}</span>
            </div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Visibility</span>
              <span>{repo.visibility || 'unknown'}</span>
            </div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Primary Language</span>
              <span>{repo.language || 'Unknown'}</span>
            </div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Default Branch</span>
              <span>{repo.default_branch || 'main'}</span>
            </div>
          </section>

          <section className="panel-section telemetry-card animate-stagger" style={{ animationDelay: '120ms' }}>
            <div className="section-label">INDEXING TELEMETRY</div>
            <div className="status-pill">{status?.status || repo.status || 'ready'}</div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Indexed Chunks</span>
              <strong>{status?.chunks || repo.chunks || 0}</strong>
            </div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Semantic Map</span>
              <span className="text-accent">Active</span>
            </div>
            <div className="repo-meta-row compact">
              <span className="meta-label">Dependency Atlas</span>
              <span className="text-terracotta">Ready</span>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

function RepositoryPreparingPage() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const [repo, setRepo] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isMounted = true;

    Promise.all([api.getRepo(repoId), api.getRepoStatus(repoId)])
      .then(([repoData, statusData]) => {
        if (!isMounted) return;
        setRepo(repoData);
        setStatus(statusData);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || 'Repository preparation could not be started.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [repoId]);

  const stageStatus = status?.status || repo?.status || 'preparing';
  const isReady = stageStatus === 'ready';

  return (
    <div className="page-shell preparation-page">
      <VisualEnvironment variant="preparation" watermark={repo?.repo_name || repoId} />
      <TopNavigation />
      <main className="preparation-viewport">
        <div className="preparation-card-container">
          <div className="preparation-header-row">
            <div>
              <div className="eyebrow">BUILDING THE CODE ATLAS</div>
              <h2 className="preparation-title">{repo?.repo_name || repoId || 'Analyzing repository'}</h2>
            </div>
            <button type="button" className="secondary-button small" onClick={() => navigate('/repositories')}>
              Back to Archive
            </button>
          </div>

          {error ? <div className="inline-error" style={{ marginBottom: 16 }}>{error}</div> : null}

          {loading ? (
            <div className="panel-section preparation-card">
              <div className="telemetry-loading-spinner" />
              <div className="loading-state">Constructing architectural map & dependency graph…</div>
            </div>
          ) : (
            <div className="panel-section preparation-card animate-stagger">
              <div className="preparation-status-header">
                <div className={`status-pill ${isReady ? 'ready' : 'in-progress'}`}>
                  <span className="pulsing-dot" />
                  {stageStatus.toUpperCase()}
                </div>
                <span className="telemetry-mark inline">ATLAS EXPEDITION §01</span>
              </div>

              <div className="empty-copy preparation-subtitle">
                Constructing high-resolution code atlas, vector chunks, and dependency relationships.
              </div>

              <ul className="checklist">
                <li className="step-complete">Repository connected & cloned</li>
                <li className="step-complete">Files scanned & partitioned</li>
                <li className="step-complete">Code chunks created & vectorized</li>
                <li className="step-complete">Semantic index constructed</li>
                <li className="step-complete">Dependency relationships analyzed</li>
                <li className={isReady ? 'step-complete' : 'step-pending'}>
                  {isReady ? 'Repository atlas ready for exploration' : 'Finalizing repository index…'}
                </li>
              </ul>

              <div className="preparation-meta-box">
                <div className="repo-meta-row compact">
                  <span className="meta-label">Owner</span>
                  <span>{repo?.owner || 'unknown'}</span>
                </div>
                <div className="repo-meta-row compact">
                  <span className="meta-label">Repository</span>
                  <span>{repo?.full_name || repo?.repo_name || repoId}</span>
                </div>
                {repo?.language ? (
                  <div className="repo-meta-row compact">
                    <span className="meta-label">Language</span>
                    <span>{repo.language}</span>
                  </div>
                ) : null}
              </div>

              <div className="preparation-actions">
                {isReady ? (
                  <button
                    type="button"
                    className="primary-button full-width enter-workspace-btn"
                    onClick={() => navigate(`/workspace/${encodeURIComponent(repoId)}`)}
                  >
                    Open RepoSage Workspace →
                  </button>
                ) : (
                  <button
                    type="button"
                    className="secondary-button full-width"
                    onClick={() => navigate(`/repositories/${encodeURIComponent(repoId)}/prepare`)}
                  >
                    Refresh status
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function WorkspacePage() {
  const { repoId } = useParams();
  const [selectedRepo, setSelectedRepo] = useState(null);

  const [question, setQuestion] = useState('');
  const [isQueryLoading, setIsQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState('');
  const [answer, setAnswer] = useState(null);

  const [selectedFunction, setSelectedFunction] = useState('');
  const [graphData, setGraphData] = useState(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState('');

  const [openTabs, setOpenTabs] = useState([]);
  const [activeTabPath, setActiveTabPath] = useState(null);

  useEffect(() => {
    let isMounted = true;

    api.getRepo(repoId)
      .then((data) => {
        if (isMounted) setSelectedRepo(data);
      })
      .catch(() => {
        if (isMounted) setSelectedRepo(null);
      });

    // Reset all tabs, answer, query, and graph state when repo changes
    setOpenTabs([]);
    setActiveTabPath(null);
    setAnswer(null);
    setQuestion('');
    setQueryError('');
    setSelectedFunction('');
    setGraphData(null);
    setGraphError('');

    return () => {
      isMounted = false;
    };
  }, [repoId]);

  const citations = useMemo(
    () => (Array.isArray(answer?.citations) ? answer.citations : []),
    [answer]
  );

  function handleOpenFile(filePath, startLine = null, endLine = null) {
    if (!filePath) return;
    const cleanPath = filePath.trim().replace(/^\[|\]$/g, '').split(':')[0];
    const fileName = cleanPath.split('/').pop() || cleanPath;

    setOpenTabs((prev) => {
      const existingIndex = prev.findIndex((t) => t.path === cleanPath);
      if (existingIndex >= 0) {
        const updated = [...prev];
        updated[existingIndex] = {
          ...updated[existingIndex],
          startLine: startLine ? Number(startLine) : null,
          endLine: endLine ? Number(endLine) : (startLine ? Number(startLine) : null),
        };
        return updated;
      }
      return [
        ...prev,
        {
          path: cleanPath,
          name: fileName,
          startLine: startLine ? Number(startLine) : null,
          endLine: endLine ? Number(endLine) : (startLine ? Number(startLine) : null),
        },
      ];
    });
    setActiveTabPath(cleanPath);
  }

  function handleOpenCitation(citation) {
    if (!citation || typeof citation !== 'string') return;
    const cleaned = citation.trim().replace(/^\[|\]$/g, '');
    const match = cleaned.match(/^(.*?)(?::(\d+)(?:-(\d+))?)?$/);
    if (!match) return;

    const filePath = match[1];
    const startLine = match[2] ? Number(match[2]) : null;
    const endLine = match[3] ? Number(match[3]) : (match[2] ? Number(match[2]) : null);
    handleOpenFile(filePath, startLine, endLine);
  }

  function handleSelectTab(path) {
    setActiveTabPath(path);
  }

  function handleCloseTab(path) {
    setOpenTabs((prev) => {
      const idx = prev.findIndex((t) => t.path === path);
      if (idx === -1) return prev;
      const nextTabs = prev.filter((t) => t.path !== path);
      if (activeTabPath === path) {
        if (nextTabs.length > 0) {
          const nextActiveIdx = Math.min(idx, nextTabs.length - 1);
          setActiveTabPath(nextTabs[nextActiveIdx].path);
        } else {
          setActiveTabPath(null);
        }
      }
      return nextTabs;
    });
  }

  function handleCloseAllTabs() {
    setOpenTabs([]);
    setActiveTabPath(null);
  }

  async function handleQuestionSubmit() {
    if (!selectedRepo) {
      setQueryError('Connect a repository before asking a question.');
      return;
    }

    if (!question.trim()) {
      setQueryError('Ask RepoSage about your repository.');
      return;
    }

    setIsQueryLoading(true);
    setQueryError('');
    setGraphData(null);
    setGraphError('');
    setAnswer({
      answer: '',
      citations: [],
      confidence: null,
      functions: [],
      isStreaming: true,
    });

    try {
      await api.askQuestionStream(
        {
          repo_id: selectedRepo.repo_id,
          question: question.trim(),
        },
        {
          onStart: () => {
            setAnswer({
              answer: '',
              citations: [],
              confidence: null,
              functions: [],
              isStreaming: true,
            });
          },
          onToken: (tokenText) => {
            setAnswer((prev) => ({
              ...(prev || {}),
              answer: (prev?.answer || '') + tokenText,
              isStreaming: true,
            }));
          },
          onComplete: (data) => {
            setAnswer(data);
          },
          onError: (err) => {
            setQueryError(err.message || 'Stream error occurred.');
            setAnswer(null);
          },
        }
      );
    } catch (error) {
      setQueryError(error.message || 'Unable to reach RepoSage backend.');
      setAnswer(null);
    } finally {
      setIsQueryLoading(false);
    }
  }

  async function handleResetConversation() {
    if (!selectedRepo) return;
    try {
      await api.resetConversation(selectedRepo.repo_id);
    } catch (error) {
      console.error(error);
    }
    setAnswer(null);
    setQuestion('');
    setQueryError('');
    setSelectedFunction('');
    setGraphData(null);
    setGraphError('');
  }

  async function handleGraphLoad(functionName) {
    if (!selectedRepo || !functionName || !functionName.trim()) {
      setGraphError('Enter a function name to inspect graph relationships.');
      return;
    }

    const cleanName = functionName.trim();
    setGraphLoading(true);
    setGraphError('');
    setSelectedFunction(cleanName);

    try {
      const response = await api.getGraph(selectedRepo.repo_id, cleanName);
      setGraphData(response);
      if (response?.file_path && response?.start_line) {
        handleOpenFile(response.file_path, response.start_line, response.end_line);
      }
    } catch (error) {
      setGraphError(error.message || 'Unable to load dependency graph.');
      setGraphData(null);
    } finally {
      setGraphLoading(false);
    }
  }

  return (
    <div className="page-shell workspace-page">
      <VisualEnvironment variant="workspace" watermark={selectedRepo?.repo_name} />
      <TopNavigation />
      <div className="app-shell">
        <aside className="sidebar left-sidebar">
          <div className="panel-header subtle">CODE ATLAS</div>

          {selectedRepo ? (
            <div className="panel-section repo-summary">
              <div className="repo-pill active">Active Atlas</div>
              <div className="repo-name">{selectedRepo.full_name || selectedRepo.repo_name || selectedRepo.repo_id}</div>
              <div className="repo-meta-row">
                <span className="meta-label">Owner</span>
                <span>{selectedRepo.owner || 'unknown'}</span>
              </div>
              <div className="repo-meta-row">
                <span className="meta-label">Chunks indexed</span>
                <span>{selectedRepo.chunks || 0}</span>
              </div>
            </div>
          ) : null}

          <ExplorerPanel
            selectedRepo={selectedRepo}
            activeFilePath={activeTabPath}
            onSelectFile={(filePath, line) => handleOpenFile(filePath, line, line)}
          />
        </aside>

        <main className="workspace-panel">
          <header className="topbar">
            <div className="workspace-header-info">
              <div className="eyebrow">REPOSAGE WORKSPACE</div>
              <div className="workspace-title">
                Repository: <strong>{selectedRepo ? selectedRepo.repo_name || selectedRepo.repo_id : 'No repository selected'}</strong>
              </div>
            </div>

            {selectedRepo ? (
              <div className="workspace-meta-badges">
                {selectedRepo.language ? (
                  <span className="meta-badge language-badge">{selectedRepo.language}</span>
                ) : null}
                {selectedRepo.default_branch ? (
                  <span className="meta-badge branch-badge">⎇ {selectedRepo.default_branch}</span>
                ) : null}
                <span className={`meta-badge visibility-badge ${selectedRepo.private ? 'private' : 'public'}`}>
                  {selectedRepo.private ? 'Private' : 'Public'}
                </span>
                {typeof selectedRepo.files_indexed === 'number' && selectedRepo.files_indexed > 0 ? (
                  <span className="meta-badge stat-badge">{selectedRepo.files_indexed} files</span>
                ) : null}
                {typeof selectedRepo.chunks === 'number' ? (
                  <span className="meta-badge stat-badge">{selectedRepo.chunks} chunks</span>
                ) : null}
              </div>
            ) : null}
          </header>

          <div className="workspace-body">
            <div className="query-panel">
              <QueryComposer
                value={question}
                onChange={setQuestion}
                onSubmit={handleQuestionSubmit}
                onResetConversation={handleResetConversation}
                isLoading={isQueryLoading}
                disabled={!selectedRepo}
                placeholder="Ask anything about your codebase..."
                suggestions={suggestedQuestions}
              />

              {queryError ? <div className="inline-error margin-top">{queryError}</div> : null}
            </div>

            <AnswerPanel
              answer={answer}
              isLoading={isQueryLoading}
              error={queryError}
              citations={citations}
              onSelectCitation={handleOpenCitation}
              onInspectGraph={handleGraphLoad}
            />

            <SourceViewer
              selectedRepo={selectedRepo}
              openTabs={openTabs}
              activeTabPath={activeTabPath}
              onSelectTab={handleSelectTab}
              onCloseTab={handleCloseTab}
              onCloseAllTabs={handleCloseAllTabs}
            />
          </div>
        </main>

        <aside className="sidebar right-sidebar">
          <div className="panel-header subtle">ENGINEERING CONTEXT</div>

          <EngineeringContext
            graphData={graphData}
            graphLoading={graphLoading}
            graphError={graphError}
            selectedFunction={selectedFunction}
            onFunctionChange={setSelectedFunction}
            onInspectGraph={handleGraphLoad}
            onNavigateToSource={(filePath, startLine, endLine) => handleOpenFile(filePath, startLine, endLine)}
          />
        </aside>
      </div>
      <StatusBar selectedRepo={selectedRepo} />
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/auth/callback" element={<AuthCallbackPage />} />
          <Route
            path="/repositories"
            element={
              <ProtectedRoute>
                <RepositorySelectionPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/repositories/:repoId/prepare"
            element={
              <ProtectedRoute>
                <RepositoryPreparingPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/repositories/:repoId"
            element={
              <ProtectedRoute>
                <RepositoryOverviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workspace/:repoId"
            element={
              <ProtectedRoute>
                <WorkspacePage />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
