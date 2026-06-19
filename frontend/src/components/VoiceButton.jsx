import React from 'react'

const stateConfig = {
  idle: { label: 'Click to start', color: '#475569', icon: 'mic' },
  connecting: { label: 'Connecting...', color: '#f59e0b', icon: 'spinner' },
  ready: { label: 'Listening for speech...', color: '#22c55e', icon: 'mic' },
  listening: { label: 'Speech detected', color: '#ef4444', icon: 'pulse' },
  processing: { label: 'Processing...', color: '#8b5cf6', icon: 'spinner' },
  speaking: { label: 'Agent speaking...', color: '#3b82f6', icon: 'wave' },
}

export default function VoiceButton({
  sessionState,
  onStartSession,
  onEndSession,
  audioLevel,
  vadActive,
}) {
  const config = stateConfig[sessionState] || stateConfig.idle
  const isActive = sessionState !== 'idle' && sessionState !== 'connecting'
  const isClickable = sessionState === 'idle' || isActive

  const handleClick = () => {
    if (sessionState === 'idle') {
      onStartSession()
    } else if (isActive) {
      onEndSession()
    }
  }

  const levelScale = sessionState === 'ready' || sessionState === 'listening'
    ? 1 + Math.min(audioLevel * 8, 0.4)
    : 1

  const ringOpacity = sessionState === 'ready' || sessionState === 'listening'
    ? Math.min(audioLevel * 15, 1)
    : 0

  return (
    <div style={styles.wrapper}>
      {/* Audio level ring */}
      <div
        style={{
          ...styles.levelRing,
          transform: `scale(${levelScale})`,
          opacity: ringOpacity,
          borderColor: vadActive ? '#ef4444' : '#22c55e',
          boxShadow: vadActive
            ? '0 0 30px rgba(239,68,68,0.4)'
            : `0 0 ${20 * ringOpacity}px rgba(34,197,94,0.2)`,
        }}
      />

      <button
        onClick={handleClick}
        disabled={!isClickable}
        style={{
          ...styles.button,
          background: config.color,
          cursor: isClickable ? 'pointer' : 'default',
          animation: sessionState === 'listening' ? 'pulse 1.5s infinite' : 'none',
          boxShadow: `0 0 ${sessionState === 'listening' ? '30px' : '15px'} ${config.color}40`,
        }}
      >
        {config.icon === 'mic' && <MicIcon />}
        {config.icon === 'spinner' && <SpinnerIcon />}
        {config.icon === 'pulse' && <MicIcon />}
        {config.icon === 'wave' && <WaveIcon />}
      </button>

      <span style={styles.label}>{config.label}</span>

      {/* VAD status badge */}
      {(sessionState === 'ready' || sessionState === 'listening') && (
        <div style={styles.vadRow}>
          <span
            style={{
              ...styles.vadDot,
              background: vadActive ? '#ef4444' : '#22c55e',
              boxShadow: vadActive
                ? '0 0 8px rgba(239,68,68,0.6)'
                : '0 0 6px rgba(34,197,94,0.4)',
            }}
          />
          <span style={styles.vadLabel}>
            {vadActive ? 'Voice detected' : 'Waiting for speech'}
          </span>
        </div>
      )}

      {isActive && (
        <button onClick={onEndSession} style={styles.endButton}>
          End Conversation
        </button>
      )}

      <style>{`
        @keyframes pulse {
          0% { transform: scale(1); }
          50% { transform: scale(1.08); }
          100% { transform: scale(1); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

function MicIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="1" width="6" height="12" rx="3" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" style={{ animation: 'spin 1s linear infinite' }}>
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  )
}

function WaveIcon() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2">
      <line x1="4" y1="8" x2="4" y2="16" />
      <line x1="8" y1="5" x2="8" y2="19" />
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="16" y1="5" x2="16" y2="19" />
      <line x1="20" y1="8" x2="20" y2="16" />
    </svg>
  )
}

const styles = {
  wrapper: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '12px',
    position: 'relative',
  },
  levelRing: {
    position: 'absolute',
    top: '-8px',
    width: '96px',
    height: '96px',
    borderRadius: '50%',
    border: '3px solid',
    transition: 'transform 0.1s ease, opacity 0.1s ease, border-color 0.2s ease',
    pointerEvents: 'none',
  },
  button: {
    width: '80px',
    height: '80px',
    borderRadius: '50%',
    border: 'none',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.3s ease',
    zIndex: 1,
  },
  label: {
    fontSize: '14px',
    color: '#94a3b8',
    fontWeight: 500,
  },
  vadRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  vadDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    transition: 'all 0.2s ease',
  },
  vadLabel: {
    fontSize: '12px',
    color: '#64748b',
  },
  endButton: {
    marginTop: '8px',
    padding: '6px 16px',
    fontSize: '12px',
    color: '#94a3b8',
    background: 'transparent',
    border: '1px solid #334155',
    borderRadius: '6px',
    cursor: 'pointer',
    transition: 'all 0.2s ease',
  },
}
