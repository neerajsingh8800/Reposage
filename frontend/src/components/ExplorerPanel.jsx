import { useEffect, useMemo, useState } from 'react';
import { api } from '../lib/api';

export function ExplorerPanel({ selectedRepo, activeFilePath, onSelectFile }) {
  const [treeItems, setTreeItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedDirs, setExpandedDirs] = useState({});
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    if (!selectedRepo) {
      setTreeItems([]);
      setExpandedDirs({});
      setSearchQuery('');
      setSearchResults([]);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError('');

    api.getRepoTree(selectedRepo.repo_id)
      .then((res) => {
        if (!isMounted) return;
        const items = res.items || [];
        setTreeItems(items);
        // Expand root directories by default
        const initialExpanded = {};
        items.forEach((item) => {
          if (item.type === 'directory') {
            const depth = item.path.split('/').length;
            if (depth <= 2) {
              initialExpanded[item.path] = true;
            }
          }
        });
        setExpandedDirs(initialExpanded);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || 'Unable to load file tree.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedRepo?.repo_id]);

  // Handle repository search
  useEffect(() => {
    if (!selectedRepo || !searchQuery.trim()) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    let isMounted = true;
    const timer = setTimeout(() => {
      setIsSearching(true);
      api.searchRepo(selectedRepo.repo_id, searchQuery.trim())
        .then((res) => {
          if (!isMounted) return;
          setSearchResults(res.results || []);
        })
        .catch(() => {
          if (!isMounted) return;
          setSearchResults([]);
        })
        .finally(() => {
          if (!isMounted) setIsSearching(false);
        });
    }, 250);

    return () => {
      isMounted = false;
      clearTimeout(timer);
    };
  }, [selectedRepo?.repo_id, searchQuery]);

  function toggleDir(dirPath, e) {
    e.stopPropagation();
    setExpandedDirs((prev) => ({
      ...prev,
      [dirPath]: !prev[dirPath],
    }));
  }

  // Filter visible tree items based on expanded directory state
  const visibleTreeItems = useMemo(() => {
    const result = [];
    for (const item of treeItems) {
      const parts = item.path.split('/');
      let isVisible = true;
      // Check if all parent directories are expanded
      for (let i = 1; i < parts.length; i++) {
        const parentPath = parts.slice(0, i).join('/');
        if (!expandedDirs[parentPath]) {
          isVisible = false;
          break;
        }
      }
      if (isVisible) {
        result.push(item);
      }
    }
    return result;
  }, [treeItems, expandedDirs]);

  return (
    <div className="panel-section explorer-panel">
      <div className="section-label">CODE ATLAS EXPLORER</div>

      {!selectedRepo ? (
        <div className="explorer-empty">
          <div className="empty-cartographic-icon">◬</div>
          <div className="empty-title">Your code atlas is ready.</div>
          <div className="empty-copy">Connect a repository to begin navigating its architectural landscape.</div>
        </div>
      ) : (
        <>
          <div className="explorer-search-box">
            <input
              type="text"
              className="explorer-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search atlas files or code..."
            />
            {searchQuery ? (
              <button
                type="button"
                className="explorer-search-clear"
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                ✕
              </button>
            ) : null}
          </div>

          {searchQuery.trim() ? (
            <div className="explorer-search-results">
              {isSearching ? (
                <div className="loading-state small">Searching codebase…</div>
              ) : searchResults.length === 0 ? (
                <div className="empty-copy">No matching files or symbols found.</div>
              ) : (
                <div className="search-result-list">
                  {searchResults.map((res) => (
                    <div
                      key={res.path}
                      className="search-result-item"
                      onClick={() => onSelectFile?.(res.path, res.line)}
                    >
                      <div className="search-result-header">
                        <span className="file-icon">📄</span>
                        <span className="search-result-path">{res.path}</span>
                        {res.line ? <span className="search-result-line">:L{res.line}</span> : null}
                      </div>
                      {res.matches && res.matches.length > 0 ? (
                        <div className="search-match-preview">
                          {res.matches.slice(0, 2).map((m, idx) => (
                            <div key={idx} className="match-snippet">
                              <span className="snippet-line">{m.line}:</span> {m.text}
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : loading ? (
            <div className="loading-state small">Constructing file tree…</div>
          ) : error ? (
            <div className="inline-error">{error}</div>
          ) : treeItems.length === 0 ? (
            <div className="empty-copy">No files found in repository.</div>
          ) : (
            <div className="tree-list stack-list compact-list">
              {visibleTreeItems.map((item) => {
                const depth = item.path.split('/').length - 1;
                const isDir = item.type === 'directory';
                const isExpanded = expandedDirs[item.path];
                const isActive = activeFilePath === item.path;

                return (
                  <div
                    key={item.path}
                    className={`tree-item ${isDir ? 'tree-dir' : 'tree-file'} ${isActive ? 'active' : ''}`}
                    style={{ paddingLeft: `${8 + depth * 14}px` }}
                    onClick={(e) => {
                      if (isDir) {
                        toggleDir(item.path, e);
                      } else {
                        onSelectFile?.(item.path);
                      }
                    }}
                  >
                    {isDir ? (
                      <span className={`tree-toggle ${isExpanded ? 'open' : ''}`}>▾</span>
                    ) : (
                      <span className="tree-indent-spacer" />
                    )}
                    <span className="tree-icon">{isDir ? (isExpanded ? '📂' : '📁') : '📄'}</span>
                    <span className="tree-name" title={item.path}>
                      {item.name || item.path.split('/').pop()}
                    </span>
                    {item.size ? (
                      <span className="tree-size">
                        {item.size < 1024 ? `${item.size} B` : `${(item.size / 1024).toFixed(0)} KB`}
                      </span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
