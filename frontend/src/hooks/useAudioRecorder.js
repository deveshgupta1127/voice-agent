import { useRef, useState, useCallback } from 'react'
import { float32ToPcm16Base64 } from '../utils/audio.js'

const SPEECH_THRESHOLD = 0.025
const SILENCE_THRESHOLD = 0.015
const SILENCE_DURATION_MS = 1500
const SPEECH_MIN_MS = 250
const PRE_BUFFER_COUNT = 4

export default function useAudioRecorder({ onAudioChunk, onSpeechStart, onSpeechEnd }) {
  const [isMonitoring, setIsMonitoring] = useState(false)
  const [vadActive, setVadActive] = useState(false)
  const [audioLevel, setAudioLevel] = useState(0)
  const [error, setError] = useState(null)

  const streamRef = useRef(null)
  const contextRef = useRef(null)
  const processorRef = useRef(null)
  const sourceRef = useRef(null)

  const vadStateRef = useRef('silence')
  const silenceStartRef = useRef(0)
  const speechStartRef = useRef(0)
  const preBufferRef = useRef([])
  const pausedRef = useRef(false)

  const onAudioChunkRef = useRef(onAudioChunk)
  const onSpeechStartRef = useRef(onSpeechStart)
  const onSpeechEndRef = useRef(onSpeechEnd)
  onAudioChunkRef.current = onAudioChunk
  onSpeechStartRef.current = onSpeechStart
  onSpeechEndRef.current = onSpeechEnd

  const startMonitoring = useCallback(async () => {
    try {
      setError(null)

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream

      const context = new AudioContext({ sampleRate: 16000 })
      contextRef.current = context

      const source = context.createMediaStreamSource(stream)
      sourceRef.current = source

      const processor = context.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      vadStateRef.current = 'silence'
      preBufferRef.current = []
      pausedRef.current = false

      processor.onaudioprocess = (e) => {
        const input = e.inputBuffer.getChannelData(0)

        let sum = 0
        for (let i = 0; i < input.length; i++) {
          sum += input[i] * input[i]
        }
        const rms = Math.sqrt(sum / input.length)
        setAudioLevel(rms)

        if (pausedRef.current) return

        const pcmB64 = float32ToPcm16Base64(input)
        const now = Date.now()
        const state = vadStateRef.current

        if (state === 'silence') {
          preBufferRef.current.push(pcmB64)
          if (preBufferRef.current.length > PRE_BUFFER_COUNT) {
            preBufferRef.current.shift()
          }

          if (rms > SPEECH_THRESHOLD) {
            vadStateRef.current = 'speech'
            speechStartRef.current = now
            setVadActive(true)

            for (const chunk of preBufferRef.current) {
              onAudioChunkRef.current(chunk)
            }
            preBufferRef.current = []
            onAudioChunkRef.current(pcmB64)
            onSpeechStartRef.current()
          }
        } else if (state === 'speech') {
          onAudioChunkRef.current(pcmB64)

          if (rms < SILENCE_THRESHOLD) {
            vadStateRef.current = 'trailing_silence'
            silenceStartRef.current = now
          }
        } else if (state === 'trailing_silence') {
          onAudioChunkRef.current(pcmB64)

          if (rms > SPEECH_THRESHOLD) {
            vadStateRef.current = 'speech'
          } else if (now - silenceStartRef.current > SILENCE_DURATION_MS) {
            const speechDuration = now - speechStartRef.current
            if (speechDuration > SPEECH_MIN_MS) {
              vadStateRef.current = 'ended'
              setVadActive(false)
              onSpeechEndRef.current()
            } else {
              vadStateRef.current = 'silence'
              setVadActive(false)
            }
          }
        }
      }

      source.connect(processor)
      processor.connect(context.destination)
      setIsMonitoring(true)
    } catch (err) {
      setError(err.name === 'NotAllowedError' ? 'Microphone permission denied' : err.message)
    }
  }, [])

  const stopMonitoring = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    if (contextRef.current) {
      contextRef.current.close()
      contextRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    vadStateRef.current = 'silence'
    pausedRef.current = false
    preBufferRef.current = []
    setIsMonitoring(false)
    setVadActive(false)
    setAudioLevel(0)
  }, [])

  const pauseVAD = useCallback(() => {
    pausedRef.current = true
    setVadActive(false)
  }, [])

  const resumeVAD = useCallback(() => {
    pausedRef.current = false
    vadStateRef.current = 'silence'
    preBufferRef.current = []
  }, [])

  return {
    startMonitoring,
    stopMonitoring,
    pauseVAD,
    resumeVAD,
    isMonitoring,
    vadActive,
    audioLevel,
    error,
  }
}
