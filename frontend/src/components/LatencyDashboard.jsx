import React from 'react'

const segments = [
  { key: 'stt_ms', label: 'STT', color: '#22c55e' },
  { key: 'llm_first_token_ms', label: 'LLM (1st token)', color: '#8b5cf6' },
  { key: 'llm_total_ms', label: 'LLM Total', color: '#a78bfa' },
  { key: 'tts_total_ms', label: 'TTS', color: '#3b82f6' },
]

export default function LatencyDashboard({ metrics }) {
  const total = metrics?.total_ms

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span>Latency</span>
        {total != null && (
          <span style={styles.total}>{Math.round(total)}ms total</span>
        )}
      </div>
      <div style={styles.body}>
        {!metrics ? (
          <div style={styles.empty}>Metrics will appear after the first turn</div>
        ) : (
          <>
            <div style={styles.barContainer}>
              {segments.map((seg) => {
                const val = metrics[seg.key]
                if (val == null || total == null || total === 0) return null
                const pct = Math.max((val / total) * 100, 5)
                return (
                  <div
                    key={seg.key}
                    style={{
                      ...styles.barSegment,
                      width: `${pct}%`,
                      background: seg.color,
                    }}
                    title={`${seg.label}: ${Math.round(val)}ms`}
                  />
                )
              })}
            </div>
            <div style={styles.legend}>
              {segments.map((seg) => {
                const val = metrics[seg.key]
                if (val == null) return null
                return (
                  <div key={seg.key} style={styles.legendItem}>
                    <span style={{ ...styles.dot, background: seg.color }} />
                    <span style={styles.legendLabel}>{seg.label}</span>
                    <span style={styles.legendValue}>{Math.round(val)}ms</span>
                  </div>
                )
              })}
              {metrics.tool_calls_ms > 0 && (
                <div style={styles.legendItem}>
                  <span style={{ ...styles.dot, background: '#f59e0b' }} />
                  <span style={styles.legendLabel}>Tools</span>
                  <span style={styles.legendValue}>{Math.round(metrics.tool_calls_ms)}ms</span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: {
    background: '#1e293b',
    borderRadius: '12px',
    overflow: 'hidden',
  },
  header: {
    padding: '12px 16px',
    fontSize: '13px',
    fontWeight: 600,
    color: '#94a3b8',
    borderBottom: '1px solid #334155',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  total: {
    fontSize: '14px',
    color: '#e2e8f0',
    fontWeight: 700,
    textTransform: 'none',
  },
  body: {
    padding: '16px',
  },
  empty: {
    textAlign: 'center',
    color: '#475569',
    fontSize: '13px',
  },
  barContainer: {
    display: 'flex',
    height: '24px',
    borderRadius: '6px',
    overflow: 'hidden',
    gap: '2px',
    marginBottom: '12px',
  },
  barSegment: {
    height: '100%',
    borderRadius: '3px',
    transition: 'width 0.3s ease',
  },
  legend: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '12px',
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  dot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    display: 'inline-block',
  },
  legendLabel: {
    fontSize: '12px',
    color: '#94a3b8',
  },
  legendValue: {
    fontSize: '12px',
    color: '#e2e8f0',
    fontWeight: 600,
    fontFamily: 'monospace',
  },
}
