import React from 'react'

const models = [
  { value: 'anthropic', label: 'Claude (Anthropic)' },
]

export default function ModelSelector({ selectedModel, onModelChange, disabled }) {
  return (
    <div style={styles.container}>
      <label style={styles.label}>LLM Provider</label>
      <select
        value={selectedModel}
        onChange={(e) => onModelChange(e.target.value)}
        disabled={disabled}
        style={{
          ...styles.select,
          opacity: disabled ? 0.5 : 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
        }}
      >
        {models.map((m) => (
          <option key={m.value} value={m.value}>
            {m.label}
          </option>
        ))}
      </select>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  label: {
    fontSize: '13px',
    color: '#94a3b8',
    fontWeight: 500,
  },
  select: {
    background: '#1e293b',
    color: '#e2e8f0',
    border: '1px solid #334155',
    borderRadius: '6px',
    padding: '6px 12px',
    fontSize: '13px',
    outline: 'none',
  },
}
