// Single source of truth for agent identity in the UI.

export const AGENT_LABELS = {
  router: 'Banking Assistant',
  card_agent: 'Card Services',
  account_agent: 'Account Services',
  transaction_agent: 'Transaction Services',
  payment_agent: 'Payment Services',
}

export const AGENT_COLORS = {
  router: '#60a5fa',
  card_agent: '#f472b6',
  account_agent: '#fbbf24',
  transaction_agent: '#34d399',
  payment_agent: '#a78bfa',
}

export function agentLabel(name) {
  return AGENT_LABELS[name] || 'Assistant'
}

export function agentColor(name) {
  return AGENT_COLORS[name] || '#94a3b8'
}

// Handover / control markers are an internal protocol — the customer must never
// see them. Strip complete markers and any trailing partial marker still streaming.
const MARKER_RE = /\[\s*HANDOVER:\s*\w+\s*\]|\[\s*END_SESSION\s*\]/gi

export function stripMarkers(text) {
  if (!text) return ''
  return text
    .replace(MARKER_RE, '')
    .replace(/\[[^\]]*$/, '') // drop an in-progress "[HANDOVER..." mid-stream
    .replace(/\s{2,}/g, ' ')
    .trim()
}
