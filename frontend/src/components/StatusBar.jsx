export function StatusBar({ selectedRepo }) {
  return (
    <footer className="status-bar">
      <div className="status-left">
        <span className="status-indicator-dot" />
        <div className="status-item">
          <span className="meta-label">INDEX:</span>
          <span>{selectedRepo ? `${selectedRepo.chunks ?? 0} AST chunks` : 'Ready'}</span>
        </div>
      </div>

      {selectedRepo ? (
        <div className="status-right" title={selectedRepo.repo_id}>
          <span className="meta-label">ACTIVE REPO:</span>
          <span>{selectedRepo.repo_name || selectedRepo.repo_id}</span>
        </div>
      ) : null}
    </footer>
  );
}
