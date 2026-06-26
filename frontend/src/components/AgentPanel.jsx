import React from 'react'
import { agentLabel, agentColor } from '../agents.js'

// Build the visited-agent path from the handoff history.
// handoffs: [{ from, to, at }]
function buildTrail(handoffs, currentAgent) {
  if (!handoffs || handoffs.length === 0) return [currentAgent]
  const path = [handoffs[0].from]
  for (const h of handoffs) path.push(h.to)
  return path
}

export default function AgentPanel({ currentAgent, handoffs }) {
  const color = agentColor(currentAgent)
  const fullTrail = buildTrail(handoffs, currentAgent)
  const trail = fullTrail.slice(-6) // keep the panel compact on long sessions
  const truncated = fullTrail.length > trail.length
  const handoffCount = handoffs ? handoffs.length : 0

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span>Active Agent</span>
        {handoffCount > 0 && (
          <span style={styles.count}>{handoffCount} handoff{handoffCount > 1 ? 's' : ''}</span>
        )}
      </div>

      <div style={styles.body}>
        {/* Active agent card — re-keyed on change so the glow animation replays */}
        <div key={currentAgent} style={{ ...styles.activeCard, borderColor: `${color}66`, animation: 'agentGlow 0.9s ease' }}>
          <span style={{ ...styles.activeDot, background: color, boxShadow: `0 0 10px ${color}` }} />
          <div style={styles.activeText}>
            <div style={{ ...styles.activeName, color }}>{agentLabel(currentAgent)}</div>
            <div style={styles.activeSub}>handling your call</div>
          </div>
        </div>

        {/* Routing trail */}
        {trail.length > 1 && (
          <div style={styles.trail}>
            <div style={styles.trailHeader}>Routing path{truncated ? ' (recent)' : ''}</div>
            {trail.map((a, i) => {
              const c = agentColor(a)
              const isLast = i === trail.length - 1
              return (
                <div key={`${a}-${i}`} style={styles.trailRow}>
                  <div style={styles.trailMarker}>
                    <span style={{ ...styles.trailDot, background: c, boxShadow: isLast ? `0 0 8px ${c}` : 'none' }} />
                    {!isLast && <span style={styles.trailLine} />}
                  </div>
                  <span style={{ ...styles.trailLabel, color: isLast ? c : '#94a3b8', fontWeight: isLast ? 700 : 500 }}>
                    {agentLabel(a)}
                  </span>
                </div>
              )
            })}
          </div>
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
  count: {
    fontSize: '11px',
    color: '#cbd5e1',
    background: '#0f172a',
    padding: '2px 8px',
    borderRadius: '10px',
    textTransform: 'none',
    letterSpacing: 0,
  },
  body: {
    padding: '14px',
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
  },
  activeCard: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '12px 14px',
    background: '#0f172a',
    borderRadius: '10px',
    border: '1px solid',
  },
  activeDot: {
    width: '12px',
    height: '12px',
    borderRadius: '50%',
    flexShrink: 0,
  },
  activeText: { display: 'flex', flexDirection: 'column', gap: '2px' },
  activeName: { fontSize: '15px', fontWeight: 700, lineHeight: 1.1 },
  activeSub: { fontSize: '11px', color: '#64748b' },
  trail: { display: 'flex', flexDirection: 'column' },
  trailHeader: {
    fontSize: '11px',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: '8px',
  },
  trailRow: { display: 'flex', alignItems: 'flex-start', gap: '10px', minHeight: '26px' },
  trailMarker: { display: 'flex', flexDirection: 'column', alignItems: 'center', width: '10px' },
  trailDot: { width: '9px', height: '9px', borderRadius: '50%', marginTop: '3px' },
  trailLine: { width: '2px', flex: 1, minHeight: '14px', background: '#334155', marginTop: '2px' },
  trailLabel: { fontSize: '13px', lineHeight: '15px', paddingBottom: '6px' },
}
