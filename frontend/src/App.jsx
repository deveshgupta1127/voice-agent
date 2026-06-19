import React, { useState, useEffect, useRef, useCallback } from 'react'
import useWebSocket from './hooks/useWebSocket.js'
import useAudioRecorder from './hooks/useAudioRecorder.js'
import { AudioPlaybackQueue } from './utils/audio.js'
import ModelSelector from './components/ModelSelector.jsx'
import VoiceButton from './components/VoiceButton.jsx'
import Transcript from './components/Transcript.jsx'
import ToolCallPanel from './components/ToolCallPanel.jsx'
import LatencyDashboard from './components/LatencyDashboard.jsx'

const WS_URL = `ws://${window.location.hostname}:8000/ws`

export default function App() {
  const [sessionState, setSessionState] = useState('idle')
  const [transcriptEntries, setTranscriptEntries] = useState([])
  const [toolCalls, setToolCalls] = useState([])
  const [latencyMetrics, setLatencyMetrics] = useState(null)
  const [selectedModel, setSelectedModel] = useState('anthropic')
  const [currentAgent, setCurrentAgent] = useState('router')
  const [agentStreamText, setAgentStreamText] = useState('')

  const agentStreamRef = useRef('')
  const currentAgentRef = useRef('router')
  const audioQueueRef = useRef(new AudioPlaybackQueue(24000))
  const sessionStateRef = useRef('idle')

  const ws = useWebSocket(WS_URL)

  const onAudioChunk = useCallback(
    (pcmBase64) => {
      ws.sendMessage({ type: 'audio_chunk', data: pcmBase64 })
    },
    [ws]
  )

  const onSpeechStart = useCallback(() => {
    if (sessionStateRef.current === 'speaking') {
      audioQueueRef.current.stop()
      ws.sendMessage({ type: 'barge_in' })
    }
    setSessionState('listening')
    sessionStateRef.current = 'listening'
  }, [ws])

  const onSpeechEnd = useCallback(() => {
    ws.sendMessage({ type: 'stop_recording' })
  }, [ws])

  const recorder = useAudioRecorder({ onAudioChunk, onSpeechStart, onSpeechEnd })
  const recorderRef = useRef(recorder)
  recorderRef.current = recorder

  useEffect(() => {
    agentStreamRef.current = agentStreamText
  }, [agentStreamText])

  useEffect(() => {
    currentAgentRef.current = currentAgent
  }, [currentAgent])

  useEffect(() => {
    ws.onMessage((data) => {
      switch (data.type) {
        case 'state': {
          setSessionState(data.state)
          sessionStateRef.current = data.state

          if (data.state === 'ready' || data.state === 'speaking') {
            const rec = recorderRef.current
            if (!rec.isMonitoring) {
              rec.startMonitoring()
            } else {
              rec.resumeVAD()
            }
          } else if (data.state === 'processing') {
            recorderRef.current.pauseVAD()
          }
          break
        }

        case 'transcript_user':
          setTranscriptEntries((prev) => [
            ...prev,
            { role: 'user', text: data.text, timestamp: new Date() },
          ])
          break

        case 'transcript_agent':
          if (data.delta) {
            setAgentStreamText((prev) => prev + data.text)
          }
          break

        case 'tool_call_start':
          setToolCalls((prev) => [
            ...prev,
            {
              name: data.name,
              args: data.args,
              result: null,
              status: 'running',
              duration_ms: null,
            },
          ])
          break

        case 'tool_call_end':
          setToolCalls((prev) =>
            prev.map((tc) =>
              tc.name === data.name && tc.status === 'running'
                ? { ...tc, result: data.result, status: 'complete', duration_ms: data.duration_ms }
                : tc
            )
          )
          break

        case 'agent_handover':
          setCurrentAgent(data.to)
          break

        case 'audio_chunk':
          if (sessionStateRef.current === 'speaking') {
            audioQueueRef.current.enqueue(data.data, data.content_type || 'audio/wav')
          }
          break

        case 'latency':
          setLatencyMetrics(data.metrics)
          break

        case 'turn_complete': {
          const streamText = agentStreamRef.current
          if (streamText) {
            setTranscriptEntries((prev) => [
              ...prev,
              {
                role: 'agent',
                text: streamText,
                timestamp: new Date(),
                agent: currentAgentRef.current,
              },
            ])
          }
          setAgentStreamText('')
          agentStreamRef.current = ''
          setToolCalls([])
          break
        }

        case 'session_ended': {
          const streamText2 = agentStreamRef.current
          if (streamText2) {
            setTranscriptEntries((prev) => [
              ...prev,
              {
                role: 'agent',
                text: streamText2,
                timestamp: new Date(),
                agent: currentAgentRef.current,
              },
            ])
          }
          setAgentStreamText('')
          agentStreamRef.current = ''
          setToolCalls([])

          const endSession = () => {
            if (audioQueueRef.current.isPlaying) {
              setTimeout(endSession, 300)
              return
            }
            recorderRef.current.stopMonitoring()
            ws.sendMessage({ type: 'end_session' })
            ws.disconnect()
            setSessionState('idle')
            sessionStateRef.current = 'idle'
            setCurrentAgent('router')
            currentAgentRef.current = 'router'
          }
          setTimeout(endSession, 300)
          break
        }

        case 'error':
          console.error(`[${data.stage}] ${data.message}`)
          break
      }
    })
  }, [ws])

  const handleStartSession = useCallback(() => {
    setSessionState('connecting')
    sessionStateRef.current = 'connecting'
    ws.sendMessage({
      type: 'start_session',
      config: { llm_provider: selectedModel },
    })
    ws.connect()
  }, [ws, selectedModel])

  const handleEndSession = useCallback(() => {
    recorderRef.current.stopMonitoring()
    audioQueueRef.current.stop()
    ws.sendMessage({ type: 'end_session' })
    ws.disconnect()
    setSessionState('idle')
    sessionStateRef.current = 'idle'
    setTranscriptEntries([])
    setToolCalls([])
    setLatencyMetrics(null)
    setAgentStreamText('')
    agentStreamRef.current = ''
    setCurrentAgent('router')
    currentAgentRef.current = 'router'
  }, [ws])

  const isSessionActive = sessionState !== 'idle'

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <h1 style={styles.title}>Banking Voice Agent</h1>
        <ModelSelector
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          disabled={isSessionActive}
        />
      </header>

      <main style={styles.main}>
        <div style={styles.leftPanel}>
          <Transcript
            entries={transcriptEntries}
            agentStreamText={agentStreamText}
            currentAgent={currentAgent}
          />
        </div>

        <div style={styles.centerPanel}>
          <VoiceButton
            sessionState={sessionState}
            onStartSession={handleStartSession}
            onEndSession={handleEndSession}
            audioLevel={recorder.audioLevel}
            vadActive={recorder.vadActive}
          />
          {currentAgent !== 'router' && (
            <div style={styles.agentBadge}>
              {currentAgent === 'card_agent' ? 'Card Services' : 'Account Services'}
            </div>
          )}
          {recorder.error && <div style={styles.error}>{recorder.error}</div>}
          {ws.lastError && <div style={styles.error}>{ws.lastError}</div>}
        </div>

        <div style={styles.rightPanel}>
          <ToolCallPanel toolCalls={toolCalls} />
          <LatencyDashboard metrics={latencyMetrics} />
        </div>
      </main>

      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0; }
        }
      `}</style>
    </div>
  )
}

const styles = {
  app: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    padding: '20px',
    maxWidth: '1400px',
    margin: '0 auto',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '24px',
    padding: '0 4px',
  },
  title: {
    fontSize: '20px',
    fontWeight: 700,
    color: '#e2e8f0',
  },
  main: {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: '1fr 200px 1fr',
    gap: '24px',
    alignItems: 'start',
  },
  leftPanel: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - 120px)',
  },
  centerPanel: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '16px',
    paddingTop: '40px',
  },
  rightPanel: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  agentBadge: {
    background: '#334155',
    color: '#60a5fa',
    fontSize: '12px',
    fontWeight: 600,
    padding: '4px 12px',
    borderRadius: '12px',
  },
  error: {
    color: '#ef4444',
    fontSize: '12px',
    textAlign: 'center',
    padding: '4px 8px',
  },
}
