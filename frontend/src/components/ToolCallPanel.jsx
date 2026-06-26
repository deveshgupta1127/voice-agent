import React, { useState } from 'react'

export default function ToolCallPanel({ toolCalls }) {
  return (
    <div style={styles.container}>
      <div style={styles.header}>Tool Calls</div>
      <div style={styles.list}>
        {toolCalls.length === 0 && (
          <div style={styles.empty}>No tool calls yet</div>
        )}
        {toolCalls.map((tc, i) => (
          <ToolCallCard key={i} toolCall={tc} />
        ))}
      </div>
    </div>
  )
}

function ToolCallCard({ toolCall }) {
  const [expanded, setExpanded] = useState(false)
  const isRunning = toolCall.status === 'running'

  return (
    <div style={styles.card}>
      <div
        style={styles.cardHeader}
        onClick={() => !isRunning && setExpanded(!expanded)}
      >
        <div style={styles.cardLeft}>
          <span style={styles.statusIcon}>
            {isRunning ? '⟳' : '✓'}
          </span>
          <code style={styles.toolName}>{toolCall.name}</code>
        </div>
        {toolCall.duration_ms != null && (
          <span style={styles.duration}>{Math.round(toolCall.duration_ms)}ms</span>
        )}
      </div>

      <div style={styles.args}>
        {Object.entries(toolCall.args || {}).map(([k, v]) => (
          <span key={k} style={styles.argPill}>
            {k}: {JSON.stringify(v)}
          </span>
        ))}
      </div>

      {expanded && toolCall.result && (
        <pre style={styles.result}>
          {JSON.stringify(toolCall.result, null, 2)}
        </pre>
      )}
    </div>
  )
}

const styles = {
  container: {
    background: '#1e293b',
    borderRadius: '12px',
    overflow: 'hidden',
    border: '1px solid #293548',
  },
  header: {
    padding: '12px 16px',
    fontSize: '12px',
    fontWeight: 600,
    color: '#94a3b8',
    borderBottom: '1px solid #334155',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
  },
  list: {
    padding: '8px',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    maxHeight: '250px',
    overflowY: 'auto',
  },
  empty: {
    textAlign: 'center',
    color: '#475569',
    padding: '20px',
    fontSize: '13px',
  },
  card: {
    background: '#0f172a',
    borderRadius: '8px',
    padding: '10px 12px',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    cursor: 'pointer',
  },
  cardLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  statusIcon: {
    fontSize: '14px',
  },
  toolName: {
    fontSize: '13px',
    color: '#60a5fa',
    fontFamily: 'monospace',
  },
  duration: {
    fontSize: '12px',
    color: '#94a3b8',
    background: '#1e293b',
    padding: '2px 8px',
    borderRadius: '10px',
  },
  args: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '4px',
    marginTop: '6px',
  },
  argPill: {
    fontSize: '11px',
    color: '#94a3b8',
    background: '#1e293b',
    padding: '2px 8px',
    borderRadius: '4px',
    fontFamily: 'monospace',
  },
  result: {
    marginTop: '8px',
    padding: '8px',
    background: '#1e293b',
    borderRadius: '6px',
    fontSize: '11px',
    color: '#94a3b8',
    overflow: 'auto',
    maxHeight: '150px',
    whiteSpace: 'pre-wrap',
    fontFamily: 'monospace',
  },
}
