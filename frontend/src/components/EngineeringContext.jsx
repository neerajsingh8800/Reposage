import { useMemo, useState } from 'react';

export function EngineeringContext({
  graphData,
  graphLoading,
  graphError,
  selectedFunction,
  onFunctionChange,
  onInspectGraph,
  onNavigateToSource,
}) {
  const [activeTab, setActiveTab] = useState('flow'); // 'flow' | 'blast'

  const targetNode = graphData?.target_node || null;
  const callers = useMemo(() => graphData?.callers || [], [graphData]);
  const callees = useMemo(() => graphData?.callees || [], [graphData]);
  const blastRadius = useMemo(() => graphData?.blast_radius || {}, [graphData]);
  const nodesMap = useMemo(() => graphData?.nodes || {}, [graphData]);

  // Group blast radius by distance
  const blastByDistance = useMemo(() => {
    const grouped = {};
    for (const [nodeName, distance] of Object.entries(blastRadius)) {
      if (!grouped[distance]) grouped[distance] = [];
      grouped[distance].push(nodeName);
    }
    return grouped;
  }, [blastRadius]);

  const totalImpactCount = Object.keys(blastRadius).length;

  function getNodeMeta(nodeName) {
    if (nodesMap[nodeName]) {
      return nodesMap[nodeName];
    }
    if (nodeName === targetNode) {
      return {
        file_path: graphData?.file_path || '',
        start_line: graphData?.start_line || 1,
        end_line: graphData?.end_line || 1,
        chunk_type: graphData?.chunk_type || 'function',
      };
    }
    return null;
  }

  function formatShortName(fullName) {
    if (!fullName) return '';
    return fullName.includes('::') ? fullName.split('::').pop() : fullName;
  }

  return (
    <div className="engineering-context">
      {/* Search and Input Bar */}
      <div className="panel-section graph-search-section">
        <div className="section-label">DEPENDENCY ATLAS</div>
        <form
          className="graph-controls"
          onSubmit={(e) => {
            e.preventDefault();
            if (selectedFunction?.trim()) {
              const raw = selectedFunction.trim();
              const cleaned = raw.replace(/^(def|class|function|const|let|var|async def)\s+/, '')
                .replace(/\(.*?\)/, '')
                .replace(/[:;]+$/, '')
                .trim();
              onInspectGraph(cleaned || raw);
            }
          }}
        >
          <input
            type="text"
            className="graph-input"
            value={selectedFunction}
            onChange={(e) => onFunctionChange(e.target.value)}
            placeholder="Inspect symbol (e.g. predict_proba, get_h2h)..."
          />
          <button
            type="submit"
            className="primary-button small"
            disabled={graphLoading || !selectedFunction?.trim()}
          >
            {graphLoading ? 'Inspecting...' : 'Inspect'}
          </button>
        </form>

        {graphError ? <div className="inline-error">{graphError}</div> : null}
      </div>

      {/* Ambiguous Selection Handling */}
      {graphData?.ambiguous ? (
        <div className="panel-section ambiguous-section">
          <div className="section-label">AMBIGUOUS ATLAS MATCHES</div>
          <div className="ambiguous-title">
            Multiple symbols matched "{selectedFunction}". Choose target:
          </div>
          <div className="stack-list compact-list">
            {graphData.matches?.map((match) => (
              <button
                key={match}
                type="button"
                className="graph-pill-button"
                onClick={() => onInspectGraph(match)}
              >
                ⚡ {match}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Main Graph & Context View */}
      {targetNode ? (
        <div className="panel-section graph-visualization-section animate-fade-in">
          {/* Sub-navigation tabs */}
          <div className="graph-view-tabs">
            <button
              type="button"
              className={`graph-tab-btn ${activeTab === 'flow' ? 'active' : ''}`}
              onClick={() => setActiveTab('flow')}
            >
              Dependency Flow ({callers.length} ↑ / {callees.length} ↓)
            </button>
            <button
              type="button"
              className={`graph-tab-btn ${activeTab === 'blast' ? 'active' : ''}`}
              onClick={() => setActiveTab('blast')}
            >
              Change Impact ({totalImpactCount})
            </button>
          </div>

          {activeTab === 'flow' ? (
            <div className="visual-flow-container">
              {/* --- UPSTREAM CALLERS --- */}
              <div className="graph-layer callers-layer">
                <div className="layer-header">
                  <span className="layer-badge caller-badge">↑ UPSTREAM CALLERS</span>
                  <span className="layer-count">
                    {callers.length} {callers.length === 1 ? 'caller' : 'callers'} invoke target
                  </span>
                </div>

                {callers.length > 0 ? (
                  <div className="node-cards-list">
                    {callers.map((caller) => {
                      const meta = getNodeMeta(caller);
                      return (
                        <div key={caller} className="node-card caller-card animate-stagger">
                          <div className="node-card-main">
                            <span className="node-kind-tag">CALLER</span>
                            <span className="node-name" title={caller}>
                              {formatShortName(caller)}
                            </span>
                          </div>
                          {meta?.file_path ? (
                            <div className="node-card-footer">
                              <button
                                type="button"
                                className="node-location-link"
                                onClick={() =>
                                  onNavigateToSource?.(
                                    meta.file_path,
                                    meta.start_line,
                                    meta.end_line
                                  )
                                }
                                title="Open in Source Viewer"
                              >
                                📄 {meta.file_path}:{meta.start_line}-{meta.end_line}
                              </button>
                              <button
                                type="button"
                                className="node-inspect-btn"
                                onClick={() => onInspectGraph(caller)}
                                title="Make this the inspection target"
                              >
                                ⚡ Inspect
                              </button>
                            </div>
                          ) : (
                            <div className="node-card-footer">
                              <button
                                type="button"
                                className="node-inspect-btn"
                                onClick={() => onInspectGraph(caller)}
                              >
                                ⚡ Inspect
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="empty-layer-box">No upstream callers invoke this symbol.</div>
                )}
              </div>

              {/* Animated Directional Connector Down to Target */}
              <div className="flow-arrow-connector">
                <svg className="connector-svg" viewBox="0 0 100 24" fill="none">
                  <path d="M50 0 L 50 18" stroke="rgba(97, 142, 168, 0.45)" strokeWidth="1.5" strokeDasharray="3 3" className="connector-dash" />
                  <polygon points="46,16 54,16 50,22" fill="#618ea8" />
                </svg>
                <span className="connector-label">invokes target</span>
              </div>

              {/* --- TARGET NODE --- */}
              <div className="graph-layer target-layer">
                <div className="node-card target-card">
                  <div className="node-card-header">
                    <span className="node-kind-tag target-tag">🎯 TARGET SYMBOL</span>
                    {graphData.chunk_type ? (
                      <span className="node-type-badge">{graphData.chunk_type}</span>
                    ) : null}
                  </div>
                  <div className="target-node-title" title={targetNode}>
                    {formatShortName(targetNode)}
                  </div>
                  <div className="target-full-signature">{targetNode}</div>
                  {graphData.file_path ? (
                    <div className="target-location-row">
                      <button
                        type="button"
                        className="target-location-btn"
                        onClick={() =>
                          onNavigateToSource?.(
                            graphData.file_path,
                            graphData.start_line,
                            graphData.end_line
                          )
                        }
                        title="View implementation in Source Viewer"
                      >
                        📄 {graphData.file_path}:{graphData.start_line}-{graphData.end_line}
                      </button>
                    </div>
                  ) : null}
                </div>
              </div>

              {/* Animated Directional Connector Down to Callees */}
              <div className="flow-arrow-connector">
                <svg className="connector-svg" viewBox="0 0 100 24" fill="none">
                  <path d="M50 0 L 50 18" stroke="rgba(217, 155, 67, 0.45)" strokeWidth="1.5" strokeDasharray="3 3" className="connector-dash" />
                  <polygon points="46,16 54,16 50,22" fill="#d99b43" />
                </svg>
                <span className="connector-label">target calls</span>
              </div>

              {/* --- DOWNSTREAM CALLEES --- */}
              <div className="graph-layer callees-layer">
                <div className="layer-header">
                  <span className="layer-badge callee-badge">↓ DOWNSTREAM CALLEES</span>
                  <span className="layer-count">
                    {callees.length} {callees.length === 1 ? 'callee' : 'callees'} called by target
                  </span>
                </div>

                {callees.length > 0 ? (
                  <div className="node-cards-list">
                    {callees.map((callee) => {
                      const meta = getNodeMeta(callee);
                      return (
                        <div key={callee} className="node-card callee-card animate-stagger">
                          <div className="node-card-main">
                            <span className="node-kind-tag callee-tag">CALLEE</span>
                            <span className="node-name" title={callee}>
                              {formatShortName(callee)}
                            </span>
                          </div>
                          {meta?.file_path ? (
                            <div className="node-card-footer">
                              <button
                                type="button"
                                className="node-location-link"
                                onClick={() =>
                                  onNavigateToSource?.(
                                    meta.file_path,
                                    meta.start_line,
                                    meta.end_line
                                  )
                                }
                                title="Open in Source Viewer"
                              >
                                📄 {meta.file_path}:{meta.start_line}-{meta.end_line}
                              </button>
                              <button
                                type="button"
                                className="node-inspect-btn"
                                onClick={() => onInspectGraph(callee)}
                                title="Make this the inspection target"
                              >
                                ⚡ Inspect
                              </button>
                            </div>
                          ) : (
                            <div className="node-card-footer">
                              <button
                                type="button"
                                className="node-inspect-btn"
                                onClick={() => onInspectGraph(callee)}
                              >
                                ⚡ Inspect
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="empty-layer-box">No downstream dependencies called by target.</div>
                )}
              </div>
            </div>
          ) : (
            /* --- CHANGE IMPACT MAP / BLAST RADIUS TAB --- */
            <div className="visual-blast-container">
              <div className="impact-summary-card">
                <div className="impact-summary-header">
                  <span className="impact-icon">⚡</span>
                  <div>
                    <div className="impact-title">Change Impact Analysis</div>
                    <div className="impact-subtitle">
                      Symbols that may be affected if <code>{formatShortName(targetNode)}</code> is modified
                    </div>
                  </div>
                </div>
                <div className="impact-stat-row">
                  <span className="impact-badge">
                    {totalImpactCount} {totalImpactCount === 1 ? 'affected symbol' : 'affected symbols'} in call hierarchy
                  </span>
                </div>
              </div>

              {totalImpactCount > 0 ? (
                <div className="blast-distances-list">
                  {Object.entries(blastByDistance)
                    .sort(([d1], [d2]) => Number(d1) - Number(d2))
                    .map(([distance, nodes]) => {
                      const distNum = Number(distance);
                      const isDirect = distNum === 1;
                      return (
                        <div key={distance} className="blast-distance-group">
                          <div className="distance-group-header">
                            <span
                              className={`distance-pill ${isDirect ? 'direct' : 'transitive'}`}
                            >
                              {isDirect ? '● Distance 1 (Direct Callers)' : `○ Distance ${distance} (Transitive Impact)`}
                            </span>
                          </div>
                          <div className="node-cards-list">
                            {nodes.map((nodeName) => {
                              const meta = getNodeMeta(nodeName);
                              return (
                                <div
                                  key={nodeName}
                                  className={`node-card impact-card ${isDirect ? 'direct-impact' : 'transitive-impact'} animate-stagger`}
                                >
                                  <div className="node-card-main">
                                    <span className="node-name" title={nodeName}>
                                      {formatShortName(nodeName)}
                                    </span>
                                  </div>
                                  {meta?.file_path ? (
                                    <div className="node-card-footer">
                                      <button
                                        type="button"
                                        className="node-location-link"
                                        onClick={() =>
                                          onNavigateToSource?.(
                                            meta.file_path,
                                            meta.start_line,
                                            meta.end_line
                                          )
                                        }
                                        title="Open in Source Viewer"
                                      >
                                        📄 {meta.file_path}:{meta.start_line}-{meta.end_line}
                                      </button>
                                      <button
                                        type="button"
                                        className="node-inspect-btn"
                                        onClick={() => onInspectGraph(nodeName)}
                                        title="Inspect dependency graph"
                                      >
                                        ⚡ Inspect
                                      </button>
                                    </div>
                                  ) : (
                                    <div className="node-card-footer">
                                      <button
                                        type="button"
                                        className="node-inspect-btn"
                                        onClick={() => onInspectGraph(nodeName)}
                                      >
                                        ⚡ Inspect
                                      </button>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    })}
                </div>
              ) : (
                <div className="empty-layer-box">
                  No upstream callers identified. Modifying this symbol carries zero direct caller impact.
                </div>
              )}
            </div>
          )}
        </div>
      ) : graphLoading ? (
        <div className="panel-section empty-panel">
          <div className="telemetry-loading-spinner" />
          <div className="loading-state">
            Constructing dependency atlas for "{selectedFunction}"…
          </div>
        </div>
      ) : selectedFunction && !graphData?.ambiguous && !graphData?.matches?.length ? (
        <div className="panel-section empty-panel">
          <div className="empty-title" style={{ color: 'var(--warning)', fontSize: '13px', fontWeight: 600 }}>
            Symbol not found
          </div>
          <div className="empty-state">
            No matching symbol or function for <code>{selectedFunction}</code> was found in the indexed repository chunks.
          </div>
        </div>
      ) : !graphData?.ambiguous ? (
        <div className="panel-section empty-panel">
          <div className="empty-cartographic-icon">⚡</div>
          <div className="empty-title">Select a symbol to map relationships</div>
          <div className="empty-state">
            Search a function above or click any symbol pill from the AI assistant to visualize caller/callee dependencies and change impact radius.
          </div>
        </div>
      ) : null}
    </div>
  );
}
