export function AnswerPanel({
  answer,
  isLoading,
  error,
  citations = [],
  onSelectCitation,
  onInspectGraph,
}) {
  if (error) {
    return (
      <div className="panel-section answer-panel error-panel-wrap">
        <div className="section-label">REPOSAGE ASSISTANT</div>
        <div className="error-state">
          <span className="error-icon">⚠️</span>
          <span>{error}</span>
        </div>
      </div>
    );
  }

  // Loading and no streamed content has arrived yet
  if (isLoading && (!answer || !answer.answer)) {
    return (
      <div className="panel-section answer-panel loading-answer-wrap">
        <div className="section-label">REPOSAGE ASSISTANT</div>
        <div className="loading-state">
          <div className="telemetry-loading-spinner" />
          <div>Tracing repository evidence & formulating grounded synthesis…</div>
        </div>
      </div>
    );
  }

  if (!answer || (!answer.answer && !isLoading)) {
    return (
      <div className="panel-section answer-panel empty-panel assistant-empty-state">
        <div className="section-label">REPOSAGE ASSISTANT</div>
        <div className="assistant-tagline">Explore the repository through evidence.</div>

        <div className="assistant-empty-graphic" aria-hidden="true">
          <svg viewBox="0 0 320 80" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M20 40 Q 90 10, 160 40 T 300 40" stroke="rgba(94, 166, 133, 0.35)" strokeWidth="1.5" strokeDasharray="4 4" />
            <circle cx="40" cy="35" r="4" fill="#5ea685" />
            <circle cx="160" cy="40" r="5" fill="#d97757" />
            <circle cx="280" cy="45" r="4" fill="#618ea8" />
          </svg>
        </div>

        <div className="assistant-empty-tags">
          <span className="hero-tag accent">Architecture</span>
          <span className="hero-tag">Code</span>
          <span className="hero-tag terracotta">Dependencies</span>
          <span className="hero-tag amber">Impact</span>
          <span className="hero-tag">Evidence</span>
        </div>

        <div className="empty-state" style={{ marginTop: 12 }}>
          Ask RepoSage any question about architecture, implementation, or dependencies to receive answers grounded in indexed repository chunks.
        </div>
      </div>
    );
  }

  const isStreaming = Boolean(answer.isStreaming);
  const identifiedFunctions = Array.isArray(answer.functions) ? answer.functions : [];
  const confidenceScore = typeof answer.confidence === 'number' ? answer.confidence : 0;
  const confidenceClass = confidenceScore > 0.8 ? 'high' : confidenceScore > 0.4 ? 'medium' : 'low';

  return (
    <div className="panel-section answer-panel">
      <div className="section-header-row">
        <div>
          <div className="section-label">REPOSAGE ASSISTANT</div>
          <div className="assistant-sublabel">Explore the repository through evidence.</div>
        </div>
        {isStreaming ? (
          <span className="streaming-badge">
            <span className="pulsing-dot" /> Tracing codebase…
          </span>
        ) : null}
      </div>

      <div className="answer-content">
        <div className="answer-summary">
          {answer.answer || 'No answer returned.'}
          {isStreaming ? <span className="streaming-cursor">▍</span> : null}
        </div>
      </div>

      {!isStreaming ? (
        <div className="answer-metadata-section">
          <div className="answer-meta-row">
            <div className="meta-block confidence-meta-block">
              <div className="section-label small">EVIDENCE CONFIDENCE</div>
              <div className={`confidence-value ${confidenceClass}`}>
                <div className="confidence-meter-bar">
                  <div
                    className="confidence-meter-fill"
                    style={{ width: `${Math.min(Math.max(confidenceScore * 100, 10), 100)}%` }}
                  />
                </div>
                <span>
                  {typeof answer.confidence === 'number'
                    ? `${(answer.confidence * 100).toFixed(0)}%`
                    : answer.confidence || 'n/a'}
                </span>
              </div>
            </div>
          </div>

          <div className="meta-block citation-block">
            <div className="section-label small">AUTHORITATIVE CITATIONS</div>
            <div className="citation-list">
              {citations.length ? (
                citations.map((citation) => (
                  <button
                    key={citation}
                    type="button"
                    className="citation-button"
                    onClick={() => onSelectCitation?.(citation)}
                    title="Open and highlight in Source Viewer"
                  >
                    📄 {citation}
                  </button>
                ))
              ) : (
                <div className="empty-copy">No citations available for this query.</div>
              )}
            </div>
          </div>

          {identifiedFunctions.length > 0 ? (
            <div className="meta-block symbol-block">
              <div className="section-label small">IDENTIFIED SYMBOLS (DEPENDENCY ATLAS)</div>
              <div className="symbol-list">
                {identifiedFunctions.map((sym) => (
                  <button
                    key={sym}
                    type="button"
                    className="symbol-pill"
                    onClick={() => onInspectGraph?.(sym)}
                    title="Inspect relationships in Engineering Context"
                  >
                    ⚡ {sym}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
