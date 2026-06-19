import { useRef, useState, useCallback } from 'react'
import { float32ToPcm16Base64 } from '../utils/audio.js'

export default function useAudioRecorder(onAudioChunk) {
  const [isRecording, setIsRecording] = useState(false)
  const [error, setError] = useState(null)
  const streamRef = useRef(null)
  const contextRef = useRef(null)
  const processorRef = useRef(null)

  const startRecording = useCallback(async () => {
    try {
      setError(null)
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })
      streamRef.current = stream

      const context = new AudioContext({ sampleRate: 16000 })
      contextRef.current = context

      const source = context.createMediaStreamSource(stream)
      const processor = context.createScriptProcessor(4096, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0)
        const pcmBase64 = float32ToPcm16Base64(inputData)
        onAudioChunk(pcmBase64)
      }

      source.connect(processor)
      processor.connect(context.destination)
      setIsRecording(true)
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        setError('Microphone permission denied')
      } else {
        setError(err.message)
      }
    }
  }, [onAudioChunk])

  const stopRecording = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (contextRef.current) {
      contextRef.current.close()
      contextRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    setIsRecording(false)
  }, [])

  return { startRecording, stopRecording, isRecording, error }
}
