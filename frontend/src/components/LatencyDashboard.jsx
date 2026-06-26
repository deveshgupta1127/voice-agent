import React from 'react'

const STAGES = [
  { key: 'stt_ms', label: 'STT', color: '#22c55e' },
  { key: 'llm_ms', label: 'LLM', color: '#a78bfa' },
  { key: 'tts_ms', label: 'TTS', color: '#3b82f6' },
  { key: 'wait_ms', label: 'Wait', color: '#475569' },
  { key: 'emit_ms', label: 'Send', color: '#ec4899' },
  { key: 'tool_ms', label: 'Tools', color: '#f59e0b' },
]

function fmt(ms) {
  if (ms == null) return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`
}

function TurnRow({ t, isLatest }) {
  const stageTotal = STAGES.reduce((s, st) => s + (t[st.key] || 0), 0)
  return (
    <div
      style={{
        ...styles.row,
        ...(isLatest ? styles.rowLatest : {}),
        animation: isLatest ? 'fadeInUp 0.3s ease' : 'none',
      }}
    >
      <div style={styles.rowTop}>
        <span style={styles.turnTag}>Turn {t.turn}</span>
        <span style={styles.response}>
          {fmt(t.response_ms)}
          <span style={styles.responseHint}> to respond</span>
        </span>
      </div>

      <div style={styles.bar}>
        {stageTotal > 0 &&
          STAGES.map((st) => {
            const v = t[st.key] || 0
            if (v <= 0) return null
            return (
              <div
                key={st.key}
                style={{ width: `${(v / stageTotal) * 100}%`, background: st.color, height: '100%' }}
                title={`${st.label}: ${fmt(v)}`}
              />
            )
          })}
      </div>

      <div style={styles.diag}>
        <span>
          TTS first-byte <b style={styles.diagVal}>{fmt(t.tts_ttfb_ms)}</b>
        </span>
        {t.recovery_ms > 5 && (
          <span style={styles.warn}>socket warm {fmt(t.recovery_ms)}</span>
        )}
        {t.response_ms == null && t.tts_ttfb_ms == null && (
          <span style={styles.warn}>no audio (provider stalled)</span>
        )}
      </div>

      <div style={styles.rowBottom}>
        <div style={styles.stageList}>
          {STAGES.map((st) => {
            const v = t[st.key] || 0
            if (v <= 0) return null
            return (
              <span key={st.key} style={styles.stageItem}>
                <span style={{ ...styles.stageDot, background: st.color }} />
                {st.label} {fmt(v)}
              </span>
            )
          })}
        </div>
        <span style={styles.total}>{fmt(t.total_ms)} total</span>
      </div>
    </div>
  )
}

export default function LatencyDashboard({ turns }) {
  const list = turns || []
  const withResp = list.filter((t) => t.response_ms != null)
  const avg =
    withResp.length > 0
      ? Math.round(withResp.reduce((s, t) => s + t.response_ms, 0) / withResp.length)
      : null

  // newest first
  const ordered = [...list].reverse()

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span>Latency · per turn</span>
        {avg != null && <span style={styles.avg}>avg {fmt(avg)}</span>}
      </div>
      <div style={styles.body}>
        {ordered.length === 0 ? (
          <div style={styles.empty}>Metrics will appear after the first turn</div>
        ) : (
          ordered.map((t, i) => <TurnRow key={t.turn} t={t} isLatest={i === 0} />)
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
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  avg: {
    fontSize: '12px',
    color: '#e2e8f0',
    fontWeight: 700,
    fontFamily: 'monospace',
    textTransform: 'none',
    letterSpacing: 0,
  },
  body: {
    padding: '10px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    maxHeight: '320px',
    overflowY: 'auto',
  },
  empty: {
    textAlign: 'center',
    color: '#475569',
    fontSize: '13px',
    padding: '24px 8px',
  },
  row: {
    background: '#0f172a',
    borderRadius: '8px',
    padding: '10px 12px',
    border: '1px solid transparent',
  },
  rowLatest: {
    border: '1px solid #3b82f680',
    boxShadow: '0 0 0 1px #3b82f633',
  },
  rowTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginBottom: '8px',
  },
  turnTag: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  response: {
    fontSize: '18px',
    fontWeight: 700,
    color: '#e2e8f0',
    fontFamily: 'monospace',
  },
  responseHint: {
    fontSize: '11px',
    fontWeight: 500,
    color: '#64748b',
    fontFamily: 'sans-serif',
  },
  bar: {
    display: 'flex',
    height: '8px',
    borderRadius: '4px',
    overflow: 'hidden',
    background: '#1e293b',
    gap: '1px',
  },
  diag: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    marginTop: '6px',
    fontSize: '11px',
    color: '#64748b',
    fontFamily: 'monospace',
    flexWrap: 'wrap',
  },
  diagVal: {
    color: '#38bdf8',
    fontWeight: 700,
  },
  warn: {
    color: '#fbbf24',
    background: '#78350f33',
    border: '1px solid #b4530933',
    borderRadius: '4px',
    padding: '1px 6px',
  },
  rowBottom: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: '8px',
    flexWrap: 'wrap',
    gap: '6px',
  },
  stageList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '10px',
  },
  stageItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    fontSize: '11px',
    color: '#94a3b8',
    fontFamily: 'monospace',
  },
  stageDot: { width: '7px', height: '7px', borderRadius: '50%' },
  total: {
    fontSize: '11px',
    color: '#64748b',
    fontFamily: 'monospace',
  },
}
