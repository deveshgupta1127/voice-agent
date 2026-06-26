import React, { useState, useEffect, useRef, useCallback } from 'react'
import useWebSocket from './hooks/useWebSocket.js'
import useAudioRecorder from './hooks/useAudioRecorder.js'
import { AudioPlaybackQueue } from './utils/audio.js'
import { stripMarkers } from './agents.js'
import ModelSelector from './components/ModelSelector.jsx'
import VoiceButton from './components/VoiceButton.jsx'
import Transcript from './components/Transcript.jsx'
import AgentPanel from './components/AgentPanel.jsx'
import ToolCallPanel from './components/ToolCallPanel.jsx'
import LatencyDashboard from './components/LatencyDashboard.jsx'

const WS_URL = `ws://${window.location.hostname}:8000/ws`

export default function App() {
  const [sessionState, setSessionState] = useState('idle')
  const [transcriptEntries, setTranscriptEntries] = useState([])
  const [toolCalls, setToolCalls] = useState([])
  const [turnLatencies, setTurnLatencies] = useState([])
  const [handoffs, setHandoffs] = useState([])
  const [selectedModel, setSelectedModel] = useState('anthropic')
  const [currentAgent, setCurrentAgent] = useState('router')
  const [agentStreamText, setAgentStreamText] = useState('')
  const [turnSpeaker, setTurnSpeaker] = useState(null)

  const agentStreamRef = useRef('')
  const turnSpeakerRef = useRef(null)
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
    currentAgentRef.current = currentAgent
  }, [currentAgent])

  const finalizeAgentBubble = () => {
    const streamText = agentStreamRef.current
    if (stripMarkers(streamText)) {
      setTranscriptEntries((prev) => [
        ...prev,
        {
          role: 'agent',
          text: streamText,
          timestamp: new Date(),
          // The agent that actually spoke (captured at first audible text),
          // not whoever holds control after a silent handback.
          agent: turnSpeakerRef.current || currentAgentRef.current,
        },
      ])
    }
    setAgentStreamText('')
    agentStreamRef.current = ''
    turnSpeakerRef.current = null
    setTurnSpeaker(null)
    setToolCalls([])
  }

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
          // New user utterance => new turn; reset who is speaking.
          turnSpeakerRef.current = null
          setTurnSpeaker(null)
          setTranscriptEntries((prev) => [
            ...prev,
            { role: 'user', text: data.text, timestamp: new Date() },
          ])
          break

        case 'transcript_agent':
          if (data.delta) {
            agentStreamRef.current += data.text
            setAgentStreamText(agentStreamRef.current)
            // Lock the speaking agent at the first audible (non-marker) text.
            if (turnSpeakerRef.current === null && stripMarkers(agentStreamRef.current)) {
              turnSpeakerRef.current = currentAgentRef.current
              setTurnSpeaker(currentAgentRef.current)
            }
          }
          break

        case 'tool_call_start':
          setToolCalls((prev) => [
            ...prev,
            { name: data.name, args: data.args, result: null, status: 'running', duration_ms: null },
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
          currentAgentRef.current = data.to
          setHandoffs((prev) => [...prev, { from: data.from, to: data.to, at: Date.now() }])
          break

        case 'audio_chunk':
          if (sessionStateRef.current === 'speaking') {
            audioQueueRef.current.enqueue(data.data, data.content_type || 'audio/wav')
          }
          break

        case 'turn_latency':
          setTurnLatencies((prev) => [...prev, data.metrics])
          break

        case 'turn_complete':
          finalizeAgentBubble()
          break

        case 'session_ended': {
          finalizeAgentBubble()
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
    ws.sendMessage({ type: 'start_session', config: { llm_provider: selectedModel } })
    ws.connect()
  }, [ws, selectedModel])

  const handleEndSession = useCallback(() => {
    recorderRef.current.stopMonitoring()
    audioQueueRef.current.stop()
    ws.sendMessage({ type: 'end_session' })
    ws.disconnect()
    setSessionState('idle')
    sessionStateRef.current = 'idle'
    // Keep the transcript (and tool calls / latencies) after a call ends so it
    // can still be extracted. Use the Clear button to start a fresh transcript.
    setAgentStreamText('')
    agentStreamRef.current = ''
    turnSpeakerRef.current = null
    setTurnSpeaker(null)
    setCurrentAgent('router')
    currentAgentRef.current = 'router'
  }, [ws])

  const handleClearTranscript = useCallback(() => {
    setTranscriptEntries([])
    setToolCalls([])
    setTurnLatencies([])
    setHandoffs([])
    setAgentStreamText('')
    agentStreamRef.current = ''
    turnSpeakerRef.current = null
    setTurnSpeaker(null)
  }, [])

  const isSessionActive = sessionState !== 'idle'

  return (
    <div style={styles.app}>
      <header style={styles.header}>
        <div style={styles.brand}>
          <span style={styles.brandDot} />
          <h1 style={styles.title}>Horizon Bank · Voice Agent</h1>
        </div>
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
            currentAgent={turnSpeaker || currentAgent}
            onClear={handleClearTranscript}
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
          {isSessionActive && (
            <AgentPanel currentAgent={currentAgent} handoffs={handoffs} />
          )}
          {recorder.error && <div style={styles.error}>{recorder.error}</div>}
          {ws.lastError && <div style={styles.error}>{ws.lastError}</div>}
        </div>

        <div style={styles.rightPanel}>
          <ToolCallPanel toolCalls={toolCalls} />
          <LatencyDashboard turns={turnLatencies} />
        </div>
      </main>

      <style>{`
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes agentGlow {
          0% { box-shadow: 0 0 0 0 rgba(96,165,250,0.0); transform: scale(0.98); }
          40% { box-shadow: 0 0 18px 2px rgba(96,165,250,0.35); transform: scale(1.01); }
          100% { box-shadow: 0 0 0 0 rgba(96,165,250,0.0); transform: scale(1); }
        }
        *::-webkit-scrollbar { width: 8px; height: 8px; }
        *::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        *::-webkit-scrollbar-track { background: transparent; }
      `}</style>
    </div>
  )
}

const styles = {
  app: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    padding: '20px 24px',
    maxWidth: '1440px',
    margin: '0 auto',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '20px',
    paddingBottom: '16px',
    borderBottom: '1px solid #1e293b',
  },
  brand: { display: 'flex', alignItems: 'center', gap: '10px' },
  brandDot: {
    width: '10px',
    height: '10px',
    borderRadius: '50%',
    background: '#3b82f6',
    boxShadow: '0 0 10px #3b82f6',
  },
  title: { fontSize: '18px', fontWeight: 700, color: '#f1f5f9', letterSpacing: '0.2px' },
  main: {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: '1.25fr 250px 1fr',
    gap: '20px',
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
    gap: '20px',
    paddingTop: '32px',
  },
  rightPanel: { display: 'flex', flexDirection: 'column', gap: '16px' },
  error: {
    color: '#fca5a5',
    fontSize: '12px',
    textAlign: 'center',
    padding: '6px 10px',
    background: 'rgba(239,68,68,0.1)',
    borderRadius: '8px',
    width: '100%',
  },
}
