export function RepositoryConnect({
  repoPath,
  repoId,
  onRepoPathChange,
  onRepoIdChange,
  onSubmit,
  isLoading,
  error,
}) {
  return (
    <div className="panel-section repository-connect">
      <div className="section-label">Connect repository</div>
      <form onSubmit={onSubmit} className="stack-form">
        <label className="field">
          <span>Repository path</span>
          <input
            type="text"
            value={repoPath}
            onChange={(event) => onRepoPathChange(event.target.value)}
            placeholder="sample_repo or C:/path/to/repo"
          />
        </label>

        <label className="field">
          <span>Repository ID</span>
          <input
            type="text"
            value={repoId}
            onChange={(event) => onRepoIdChange(event.target.value)}
            placeholder="sample_demo"
          />
        </label>

        <button type="submit" className="primary-button" disabled={isLoading}>
          {isLoading ? 'Connecting...' : 'Connect repository'}
        </button>
      </form>

      {error ? <div className="inline-error">{error}</div> : null}
    </div>
  );
}
