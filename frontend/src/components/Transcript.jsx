import React, { useRef, useEffect } from 'react'

const agentLabels = {
  router: 'Banking Assistant',
  card_agent: 'Card Services',
  account_agent: 'Account Services',
}

export default function Transcript({ entries, agentStreamText, currentAgent }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries, agentStreamText])

  return (
    <div style={styles.container}>
      <div style={styles.header}>Conversation</div>
      <div style={styles.messages}>
        {entries.map((entry, i) => (
          <div
            key={i}
            style={{
              ...styles.bubble,
              ...(entry.role === 'user' ? styles.userBubble : styles.agentBubble),
            }}
          >
            <div style={styles.role}>
              {entry.role === 'user'
                ? 'You'
                : agentLabels[entry.agent] || 'Agent'}
            </div>
            <div style={styles.text}>{entry.text}</div>
          </div>
        ))}

        {agentStreamText && (
          <div style={{ ...styles.bubble, ...styles.agentBubble }}>
            <div style={styles.role}>
              {agentLabels[currentAgent] || 'Agent'}
            </div>
            <div style={styles.text}>
              {agentStreamText}
              <span style={styles.cursor}>|</span>
            </div>
          </div>
        )}

        {entries.length === 0 && !agentStreamText && (
          <div style={styles.empty}>
            Start a conversation by clicking the microphone button
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

const styles = {
  container: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    background: '#1e293b',
    borderRadius: '12px',
    overflow: 'hidden',
    minHeight: '300px',
  },
  header: {
    padding: '12px 16px',
    fontSize: '13px',
    fontWeight: 600,
    color: '#94a3b8',
    borderBottom: '1px solid #334155',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  bubble: {
    maxWidth: '80%',
    padding: '10px 14px',
    borderRadius: '12px',
    fontSize: '14px',
    lineHeight: '1.5',
  },
  userBubble: {
    alignSelf: 'flex-end',
    background: '#3b82f6',
    color: '#ffffff',
    borderBottomRightRadius: '4px',
  },
  agentBubble: {
    alignSelf: 'flex-start',
    background: '#334155',
    color: '#e2e8f0',
    borderBottomLeftRadius: '4px',
  },
  role: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#94a3b8',
    marginBottom: '4px',
    textTransform: 'uppercase',
  },
  text: {
    wordBreak: 'break-word',
  },
  cursor: {
    animation: 'blink 1s infinite',
    fontWeight: 'bold',
    color: '#60a5fa',
  },
  empty: {
    textAlign: 'center',
    color: '#475569',
    padding: '40px 20px',
    fontSize: '14px',
  },
}
