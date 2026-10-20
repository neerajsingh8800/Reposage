import { useEffect, useMemo, useRef, useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-typescript';
import 'prismjs/components/prism-jsx';
import 'prismjs/components/prism-tsx';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';
import 'prismjs/components/prism-bash';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-markdown';
import 'prismjs/components/prism-c';
import 'prismjs/components/prism-cpp';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-rust';
import 'prismjs/components/prism-go';
import { api } from '../lib/api';

const PRISM_LANG_MAP = {
  python: 'python',
  py: 'python',
  javascript: 'javascript',
  js: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
  jsx: 'jsx',
  tsx: 'tsx',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  shell: 'bash',
  bash: 'bash',
  sh: 'bash',
  sql: 'sql',
  markdown: 'markdown',
  md: 'markdown',
  c: 'c',
  cpp: 'cpp',
  java: 'java',
  rust: 'rust',
  rs: 'rust',
  go: 'go',
  html: 'markup',
  css: 'css',
};

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function tokenizeToLines(code, langName) {
  if (!code) return ['&nbsp;'];
  const mappedLang = PRISM_LANG_MAP[langName?.toLowerCase()] || 'plain';
  const grammar = Prism.languages[mappedLang];

  if (!grammar) {
    return code.split('\n').map((line) => (line ? escapeHtml(line) : '&nbsp;'));
  }

  try {
    const tokens = Prism.tokenize(code, grammar);
    const lines = [[]];

    function processToken(token, parentTypes = []) {
      if (typeof token === 'string') {
        const parts = token.split('\n');
        for (let i = 0; i < parts.length; i++) {
          if (i > 0) lines.push([]);
          if (parts[i]) {
            lines[lines.length - 1].push({
              text: parts[i],
              types: parentTypes,
            });
          }
        }
      } else if (Array.isArray(token.content)) {
        const currentTypes = [...parentTypes, token.type];
        for (const child of token.content) {
          processToken(child, currentTypes);
        }
      } else {
        const currentTypes = [...parentTypes, token.type];
        processToken(token.content, currentTypes);
      }
    }

    for (const token of tokens) {
      processToken(token);
    }

    return lines.map((lineTokens) => {
      if (lineTokens.length === 0) return '&nbsp;';
      return lineTokens
        .map((t) => {
          const className = t.types.map((type) => `token ${type}`).join(' ');
          const escaped = escapeHtml(t.text);
          return className ? `<span class="${className}">${escaped}</span>` : escaped;
        })
        .join('');
    });
  } catch (err) {
    console.error('Syntax highlighting error:', err);
    return code.split('\n').map((line) => (line ? escapeHtml(line) : '&nbsp;'));
  }
}

export function SourceViewer({
  selectedRepo,
  openTabs = [],
  activeTabPath,
  onSelectTab,
  onCloseTab,
  onCloseAllTabs,
}) {
  const [fileCache, setFileCache] = useState({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  const activeTab = useMemo(
    () => openTabs.find((t) => t.path === activeTabPath) || null,
    [openTabs, activeTabPath]
  );

  const activeFilePath = activeTab?.path || null;
  const startLine = activeTab?.startLine || null;
  const endLine = activeTab?.endLine || (startLine ? startLine : null);

  const activeFileData = activeFilePath ? fileCache[activeFilePath] || null : null;
  const lineRefs = useRef({});

  // Fetch file content if not already in cache
  useEffect(() => {
    if (!selectedRepo || !activeFilePath) {
      setError('');
      setLoading(false);
      return;
    }

    if (fileCache[activeFilePath]) {
      setError('');
      setLoading(false);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError('');

    api.getFileContent(selectedRepo.repo_id, activeFilePath)
      .then((res) => {
        if (!isMounted) return;
        setFileCache((prev) => ({
          ...prev,
          [activeFilePath]: res,
        }));
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err.message || 'Could not load file source.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedRepo?.repo_id, activeFilePath, fileCache]);

  // Scroll to focused line range
  useEffect(() => {
    if (startLine && lineRefs.current[startLine]) {
      const timer = setTimeout(() => {
        lineRefs.current[startLine]?.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
        });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [startLine, activeFilePath, activeFileData]);

  function handleCopy() {
    if (!activeFileData?.content) return;
    navigator.clipboard?.writeText(activeFileData.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // Tokenized highlighted lines
  const highlightedLines = useMemo(() => {
    if (!activeFileData || activeFileData.is_binary || !activeFileData.content) {
      return [];
    }
    return tokenizeToLines(activeFileData.content, activeFileData.language || activeFilePath?.split('.').pop());
  }, [activeFileData, activeFilePath]);

  if (!selectedRepo) {
    return (
      <div className="panel-section source-viewer empty-panel">
        <div className="section-label">SOURCE VIEWER</div>
        <div className="empty-cartographic-icon">◬</div>
        <div className="empty-title">Source manuscript offline</div>
        <div className="empty-state">Connect a repository to inspect source files.</div>
      </div>
    );
  }

  if (openTabs.length === 0 || !activeTab) {
    return (
      <div className="panel-section source-viewer empty-panel">
        <div className="section-label">SOURCE VIEWER</div>
        <div className="empty-cartographic-icon">◬</div>
        <div className="empty-title">Choose a file or citation to inspect source</div>
        <div className="empty-state">Select a file from the Code Atlas or click an AI citation to open a manuscript tab.</div>
      </div>
    );
  }

  return (
    <div className="panel-section source-viewer source-viewer-card">
      {/* Tab Bar */}
      <div className="source-tab-bar">
        <div className="tab-scroll-container">
          {openTabs.map((tab) => {
            const isActive = tab.path === activeTabPath;
            const fileName = tab.name || tab.path.split('/').pop() || tab.path;
            return (
              <div
                key={tab.path}
                className={`source-tab-item ${isActive ? 'active' : ''}`}
                onClick={() => onSelectTab?.(tab.path)}
                title={tab.path}
              >
                <span className="tab-file-icon">📄</span>
                <span className="tab-file-name">{fileName}</span>
                {tab.startLine ? (
                  <span className="tab-line-badge">:L{tab.startLine}</span>
                ) : null}
                <button
                  type="button"
                  className="tab-close-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCloseTab?.(tab.path);
                  }}
                  title="Close tab"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>

        {openTabs.length > 1 ? (
          <button
            type="button"
            className="tab-clear-all-btn"
            onClick={onCloseAllTabs}
            title="Close all tabs"
          >
            Close All
          </button>
        ) : null}
      </div>

      {/* Header Info Bar */}
      <div className="source-header">
        <div className="source-header-left">
          <div className="source-file-path">{activeFilePath}</div>
          {startLine ? (
            <span className="focus-line-badge">
              Citation focus: Lines {startLine}{endLine && endLine !== startLine ? `–${endLine}` : ''}
            </span>
          ) : null}
        </div>
        <div className="source-header-right">
          {activeFileData?.language ? (
            <span className="lang-badge">{activeFileData.language}</span>
          ) : null}
          {activeFileData?.size ? (
            <span className="source-size-badge">
              {activeFileData.size < 1024
                ? `${activeFileData.size} B`
                : `${(activeFileData.size / 1024).toFixed(1)} KB`}
            </span>
          ) : null}
          <button
            type="button"
            className="copy-button small"
            onClick={handleCopy}
            title="Copy file content"
            disabled={!activeFileData?.content}
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Editor Content Area */}
      {loading ? (
        <div className="loading-state small">
          <div className="telemetry-loading-spinner" />
          <span>Loading source manuscript…</span>
        </div>
      ) : error ? (
        <div className="inline-error">{error}</div>
      ) : activeFileData?.is_binary ? (
        <div className="binary-notice">
          <div className="binary-icon">📦</div>
          <div className="binary-text">{activeFileData.content}</div>
        </div>
      ) : (
        <div className="code-viewer-container">
          {/* Line Gutter */}
          <div className="code-gutter">
            {highlightedLines.map((_, idx) => {
              const lineNum = idx + 1;
              const isHighlighted =
                startLine && lineNum >= startLine && (!endLine || lineNum <= endLine);
              return (
                <div
                  key={lineNum}
                  ref={(el) => {
                    lineRefs.current[lineNum] = el;
                  }}
                  className={`gutter-line ${isHighlighted ? 'highlighted' : ''}`}
                >
                  {lineNum}
                </div>
              );
            })}
          </div>

          {/* Syntax Highlighted Code Content */}
          <pre className="code-content-block">
            <code>
              {highlightedLines.map((lineHtml, idx) => {
                const lineNum = idx + 1;
                const isHighlighted =
                  startLine && lineNum >= startLine && (!endLine || lineNum <= endLine);
                return (
                  <div
                    key={lineNum}
                    className={`code-row ${isHighlighted ? 'highlighted-row' : ''}`}
                    dangerouslySetInnerHTML={{ __html: lineHtml }}
                  />
                );
              })}
            </code>
          </pre>
        </div>
      )}
    </div>
  );
}
