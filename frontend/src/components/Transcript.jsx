import React, { useRef, useEffect, useState } from 'react'
import { agentLabel, agentColor, stripMarkers } from '../agents.js'

function buildTranscriptText(entries) {
  return entries
    .map((entry) => {
      const isUser = entry.role === 'user'
      const text = isUser ? entry.text : stripMarkers(entry.text)
      if (!text) return null
      const who = isUser ? 'You' : agentLabel(entry.agent)
      const ts =
        entry.timestamp instanceof Date
          ? entry.timestamp.toLocaleTimeString()
          : ''
      return `${ts ? `[${ts}] ` : ''}${who}: ${text}`
    })
    .filter(Boolean)
    .join('\n')
}

export default function Transcript({ entries, agentStreamText, currentAgent, onClear }) {
  const bottomRef = useRef(null)
  const liveText = stripMarkers(agentStreamText)
  const [extracted, setExtracted] = useState(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries, agentStreamText])

  const hasContent = entries.some((e) =>
    e.role === 'user' ? e.text : stripMarkers(e.text)
  )

  const handleExtract = async () => {
    const text = buildTranscriptText(entries)
    if (!text) return

    // Copy to clipboard (best-effort — may be blocked on insecure origins).
    try {
      await navigator.clipboard?.writeText(text)
    } catch {
      /* clipboard unavailable — the download below still works */
    }

    // Download as a timestamped .txt file. Prepend a UTF-8 BOM so editors
    // (e.g. Notepad) render non-Latin scripts — Hindi, Tamil, Telugu,
    // Gujarati, etc. — correctly instead of as boxes/mojibake.
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    const BOM = '﻿'
    const blob = new Blob([BOM + text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `transcript-${stamp}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    setExtracted(true)
    setTimeout(() => setExtracted(false), 1600)
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.headerTitle}>Conversation</span>
        <div style={styles.headerActions}>
          <button
            type="button"
            onClick={handleExtract}
            disabled={!hasContent}
            title="Copy the transcript and download it as a .txt file (any language)"
            style={{
              ...styles.extractBtn,
              ...(hasContent ? {} : styles.extractBtnDisabled),
              ...(extracted ? styles.extractBtnDone : {}),
            }}
          >
            {extracted ? '✓ Extracted' : 'Extract Transcript'}
          </button>
          <button
            type="button"
            onClick={onClear}
            disabled={!hasContent}
            title="Clear the transcript and start fresh"
            style={{
              ...styles.clearBtn,
              ...(hasContent ? {} : styles.extractBtnDisabled),
            }}
          >
            Clear
          </button>
        </div>
      </div>
      <div style={styles.messages}>
        {entries.map((entry, i) => {
          const isUser = entry.role === 'user'
          const text = isUser ? entry.text : stripMarkers(entry.text)
          if (!isUser && !text) return null
          return (
            <div
              key={i}
              style={{
                ...styles.bubble,
                ...(isUser ? styles.userBubble : styles.agentBubble),
              }}
            >
              <div
                style={{
                  ...styles.role,
                  color: isUser ? '#bfdbfe' : agentColor(entry.agent),
                }}
              >
                {isUser ? 'You' : agentLabel(entry.agent)}
              </div>
              <div style={styles.text}>{text}</div>
            </div>
          )
        })}

        {liveText && (
          <div style={{ ...styles.bubble, ...styles.agentBubble }}>
            <div style={{ ...styles.role, color: agentColor(currentAgent) }}>
              {agentLabel(currentAgent)}
            </div>
            <div style={styles.text}>
              {liveText}
              <span style={styles.cursor}>▋</span>
            </div>
          </div>
        )}

        {entries.length === 0 && !liveText && (
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
    border: '1px solid #293548',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '8px',
    padding: '8px 10px 8px 16px',
    borderBottom: '1px solid #334155',
  },
  headerTitle: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
  },
  headerActions: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  clearBtn: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#94a3b8',
    background: 'transparent',
    border: '1px solid #3f4d63',
    borderRadius: '7px',
    padding: '5px 10px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    letterSpacing: '0.3px',
    transition: 'background 0.15s ease, color 0.15s ease',
  },
  extractBtn: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#cbd5e1',
    background: '#334155',
    border: '1px solid #3f4d63',
    borderRadius: '7px',
    padding: '5px 10px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    letterSpacing: '0.3px',
    transition: 'background 0.15s ease, color 0.15s ease',
  },
  extractBtnDisabled: {
    opacity: 0.4,
    cursor: 'not-allowed',
  },
  extractBtnDone: {
    color: '#bbf7d0',
    borderColor: '#15803d',
    background: '#14532d',
  },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  bubble: {
    maxWidth: '82%',
    padding: '10px 14px',
    borderRadius: '14px',
    fontSize: '14px',
    lineHeight: '1.5',
    animation: 'fadeInUp 0.25s ease',
  },
  userBubble: {
    alignSelf: 'flex-end',
    background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
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
    fontWeight: 700,
    marginBottom: '4px',
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
  },
  text: { wordBreak: 'break-word' },
  cursor: {
    animation: 'blink 1s infinite',
    fontWeight: 'bold',
    color: '#60a5fa',
    marginLeft: '1px',
  },
  empty: {
    textAlign: 'center',
    color: '#475569',
    padding: '40px 20px',
    fontSize: '14px',
  },
}
