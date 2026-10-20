export function QueryComposer({
  value,
  onChange,
  onSubmit,
  onResetConversation,
  isLoading,
  disabled,
  placeholder,
  suggestions,
}) {
  return (
    <div className="query-composer-wrapper">
      <div className="composer-header-row">
        <label className="question-label" htmlFor="repo-query">
          Ask anything about your repository
        </label>
        {onResetConversation ? (
          <button
            type="button"
            className="ghost-button small new-chat-btn"
            onClick={onResetConversation}
            disabled={disabled || isLoading}
            title="Reset conversation memory for this repository"
          >
            ↺ New Chat
          </button>
        ) : null}
      </div>

      <div className="composer-input-wrap">
        <textarea
          id="repo-query"
          className="query-box"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          rows={3}
          disabled={disabled || isLoading}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              if (value.trim() && !disabled && !isLoading) {
                onSubmit();
              }
            }
          }}
        />
      </div>

      {suggestions && suggestions.length > 0 ? (
        <div className="question-suggestions">
          <span className="suggestions-label">Explore:</span>
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="ghost-button small suggestion-chip"
              onClick={() => onChange(suggestion)}
              disabled={disabled || isLoading}
            >
              {suggestion}
            </button>
          ))}
        </div>
      ) : null}

      <div className="query-actions">
        <div className="composer-hint">Press ⌘+Enter or Ctrl+Enter to submit</div>
        <button
          type="button"
          className="primary-button submit-query-btn"
          onClick={onSubmit}
          disabled={disabled || isLoading || !value.trim()}
        >
          {isLoading ? (
            <>
              <span className="spinner-inline" /> Tracing repository evidence...
            </>
          ) : (
            'Ask RepoSage'
          )}
        </button>
      </div>
    </div>
  );
}
