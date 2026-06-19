export function float32ToPcm16Base64(float32Array) {
  const pcm16 = new Int16Array(float32Array.length)
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]))
    pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  const bytes = new Uint8Array(pcm16.buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}

export class AudioPlaybackQueue {
  constructor(sampleRate = 24000) {
    this._sampleRate = sampleRate
    this._queue = []
    this._playing = false
    this._context = null
    this._currentSource = null
    this._nextTime = 0
  }

  _getContext() {
    if (!this._context) {
      this._context = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: this._sampleRate,
      })
    }
    return this._context
  }

  enqueue(audioBase64, contentType) {
    const binary = atob(audioBase64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i)
    }

    this._queue.push(bytes.buffer)

    if (!this._playing) {
      this.play()
    }
  }

  async play() {
    if (this._playing) return
    this._playing = true
    const ctx = this._getContext()

    if (ctx.state === 'suspended') {
      await ctx.resume()
    }

    this._nextTime = ctx.currentTime

    while (this._queue.length > 0) {
      const buffer = this._queue.shift()
      try {
        const audioBuffer = await ctx.decodeAudioData(buffer.slice(0))
        const source = ctx.createBufferSource()
        source.buffer = audioBuffer
        source.connect(ctx.destination)

        const startTime = Math.max(this._nextTime, ctx.currentTime)
        source.start(startTime)
        this._currentSource = source
        this._nextTime = startTime + audioBuffer.duration

        await new Promise(resolve => {
          source.onended = resolve
          setTimeout(resolve, (audioBuffer.duration + 0.5) * 1000)
        })
      } catch (e) {
        console.warn('Audio decode error:', e)
      }
    }

    this._playing = false
  }

  stop() {
    this._queue = []
    if (this._currentSource) {
      try {
        this._currentSource.stop()
      } catch (e) {}
      this._currentSource = null
    }
    this._playing = false
  }

  get isPlaying() {
    return this._playing
  }
}
