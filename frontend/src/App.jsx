import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'

const API_URL = 'http://127.0.0.1:8000'
const WS_URL = 'ws://127.0.0.1:8000/ws/audio'

function App() {
  // State
  const [isConnected, setIsConnected] = useState(false)
  const [isMicActive, setIsMicActive] = useState(false)
  const [callStatus, setCallStatus] = useState('idle') // idle, connecting, active, ended
  const [callDuration, setCallDuration] = useState(0)
  const [settings, setSettings] = useState({
    max_call_duration: 600,
    max_silence_duration: 20
  })
  const [localSettings, setLocalSettings] = useState({
    max_call_duration: 600,
    max_silence_duration: 20
  })
  const [savedTranscripts, setSavedTranscripts] = useState([])
  const [selectedTranscript, setSelectedTranscript] = useState(null)
  const [logs, setLogs] = useState([])

  // Refs
  const wsRef = useRef(null)
  const audioContextRef = useRef(null)
  const playbackContextRef = useRef(null)
  const currentSourceRef = useRef(null)  // Track currently playing audio source
  const mediaStreamRef = useRef(null)
  const processorRef = useRef(null)
  const playbackQueueRef = useRef([])
  const isPlayingRef = useRef(false)
  const callTimerRef = useRef(null)
  const stopPlaybackRef = useRef(false)  // Flag to stop playback loop
  const pendingPlaybackCompleteRef = useRef(false)  // Send playback_complete after queue empty

  // Add log
  const addLog = useCallback((message) => {
    const timestamp = new Date().toLocaleTimeString()
    setLogs(prev => [...prev.slice(-50), `[${timestamp}] ${message}`])
  }, [])

  // Fetch settings
  const fetchSettings = async () => {
    try {
      const res = await fetch(`${API_URL}/api/settings`)
      const data = await res.json()
      setSettings(data)
      setLocalSettings(data)
    } catch (err) {
      addLog(`Error fetching settings: ${err.message}`)
    }
  }

  // Update settings
  const saveSettings = async () => {
    try {
      const res = await fetch(`${API_URL}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(localSettings)
      })
      const data = await res.json()
      setSettings(data)
      setLocalSettings(data)
      addLog(`✅ Settings saved: Duration=${data.max_call_duration}s, Silence=${data.max_silence_duration}s`)
    } catch (err) {
      addLog(`Error saving settings: ${err.message}`)
    }
  }

  // Fetch transcripts list
  const fetchTranscripts = async () => {
    try {
      const res = await fetch(`${API_URL}/api/transcripts`)
      const data = await res.json()
      setSavedTranscripts(data.transcripts || [])
    } catch (err) {
      addLog(`Error fetching transcripts: ${err.message}`)
    }
  }

  // View transcript
  const viewTranscript = async (filename) => {
    try {
      const res = await fetch(`${API_URL}/api/transcripts/${filename}`)
      const data = await res.json()
      setSelectedTranscript(data)
    } catch (err) {
      addLog(`Error fetching transcript: ${err.message}`)
    }
  }

  // Stop all current playback immediately
  const stopAllPlayback = () => {
    // Set stop flag
    stopPlaybackRef.current = true

    // Stop current audio source if playing
    if (currentSourceRef.current) {
      try {
        currentSourceRef.current.stop()
        currentSourceRef.current.disconnect()
      } catch (e) {
        // Ignore errors if already stopped
      }
      currentSourceRef.current = null
    }

    // Clear the queue
    playbackQueueRef.current = []
    isPlayingRef.current = false

    // Close and recreate playback context to stop all audio immediately
    if (playbackContextRef.current && playbackContextRef.current.state !== 'closed') {
      try {
        playbackContextRef.current.close()
      } catch (e) { }
      playbackContextRef.current = null
    }
  }

  // Play audio chunk - returns Promise that resolves when done
  const playAudioChunk = (base64Data) => {
    return new Promise((resolve, reject) => {
      // Check if we should stop
      if (stopPlaybackRef.current) {
        reject(new Error('Playback stopped'))
        return
      }

      if (!playbackContextRef.current || playbackContextRef.current.state === 'closed') {
        playbackContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
          sampleRate: 16000
        })
      }

      const ctx = playbackContextRef.current

      if (ctx.state === 'suspended') {
        ctx.resume()
      }

      const rawData = atob(base64Data)
      const bytes = new Uint8Array(rawData.length)
      for (let i = 0; i < rawData.length; i++) {
        bytes[i] = rawData.charCodeAt(i)
      }

      const int16 = new Int16Array(bytes.buffer)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768
      }

      const buffer = ctx.createBuffer(1, float32.length, 16000)
      buffer.getChannelData(0).set(float32)

      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(ctx.destination)

      // Track current source so we can stop it
      currentSourceRef.current = source

      source.onended = () => {
        currentSourceRef.current = null
        resolve()
      }

      source.start()
    })
  }

  // Process playback queue
  const processPlaybackQueue = async () => {
    if (isPlayingRef.current) return
    if (playbackQueueRef.current.length === 0) {
      // Queue is empty - if we have pending playback_complete, send it now
      if (pendingPlaybackCompleteRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
        pendingPlaybackCompleteRef.current = false
        wsRef.current.send(JSON.stringify({ type: 'playback_complete' }))
        addLog('🔈 All audio played - silence timer started')
      }
      return
    }

    isPlayingRef.current = true
    stopPlaybackRef.current = false  // Reset stop flag

    while (playbackQueueRef.current.length > 0 && !stopPlaybackRef.current) {
      const chunk = playbackQueueRef.current.shift()
      try {
        await playAudioChunk(chunk)
      } catch (err) {
        // If stopped, break out of loop
        if (stopPlaybackRef.current) break
        console.error('Playback error:', err)
      }
    }

    isPlayingRef.current = false

    // After queue is empty, check if we need to send playback_complete
    if (pendingPlaybackCompleteRef.current && !stopPlaybackRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      pendingPlaybackCompleteRef.current = false
      wsRef.current.send(JSON.stringify({ type: 'playback_complete' }))
      addLog('🔈 All audio played - silence timer started')
    }
  }

  // Start call
  const startCall = async () => {
    try {
      setCallStatus('connecting')
      addLog('🔌 Connecting to server...')

      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = async () => {
        setIsConnected(true)
        setCallStatus('active')
        addLog('✅ Connected! Starting microphone...')

        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
              sampleRate: 16000,
              channelCount: 1,
              echoCancellation: true,
              noiseSuppression: true
            }
          })
          mediaStreamRef.current = stream

          const ctx = new AudioContext({ sampleRate: 16000 })
          audioContextRef.current = ctx
          const source = ctx.createMediaStreamSource(stream)

          await ctx.audioWorklet.addModule('/audioProcessor.js')
          const processor = new AudioWorkletNode(ctx, 'audio-processor')
          processorRef.current = processor

          processor.port.onmessage = (e) => {
            if (ws.readyState === WebSocket.OPEN) {
              const int16 = new Int16Array(e.data)
              const bytes = new Uint8Array(int16.buffer)
              const base64 = btoa(String.fromCharCode(...bytes))
              ws.send(JSON.stringify({ type: 'audio', data: base64 }))
            }
          }

          source.connect(processor)
          processor.connect(ctx.destination)

          setIsMicActive(true)
          addLog('🎤 Microphone active - speak now!')

          const startTime = Date.now()
          callTimerRef.current = setInterval(() => {
            setCallDuration(Math.floor((Date.now() - startTime) / 1000))
          }, 1000)
        } catch (err) {
          addLog(`❌ Microphone error: ${err.message}`)
          ws.close()
        }
      }

      ws.onmessage = async (event) => {
        const data = JSON.parse(event.data)

        if (data.type === 'audio_chunk') {
          // Clear and stop all playback on first chunk of new response (barge-in)
          if (data.first_chunk) {
            stopAllPlayback()
            pendingPlaybackCompleteRef.current = false  // Reset pending on new response
            addLog('🔄 New response starting...')
          }
          playbackQueueRef.current.push(data.data)
          processPlaybackQueue()
        } else if (data.type === 'audio_end') {
          addLog('🔊 Agent response received, playing audio...')
          // Set flag to send playback_complete after all audio finishes
          pendingPlaybackCompleteRef.current = true
          // Trigger check in case queue is already empty
          processPlaybackQueue()
        } else if (data.type === 'call_end') {
          addLog(`📞 Call ended: ${data.reason}`)
          stopCall()
        } else if (data.type === 'barge_in') {
          // Server detected new query, stop all playback immediately
          stopAllPlayback()
          pendingPlaybackCompleteRef.current = false  // Cancel pending
          addLog('🔴 Interrupting - new query detected...')
        }
      }

      ws.onclose = () => {
        addLog('🔴 Disconnected from server')
        setIsConnected(false)
        setIsMicActive(false)
        setCallStatus('idle')  // Reset to idle so button shows "Start Call"
      }

      ws.onerror = (err) => {
        addLog(`❌ Connection error`)
        setCallStatus('idle')  // Reset to idle
        setIsConnected(false)
      }

    } catch (err) {
      addLog(`❌ Error: ${err.message}`)
      setCallStatus('idle')
    }
  }

  // Stop call
  const stopCall = () => {
    addLog('📴 Ending call...')

    if (callTimerRef.current) {
      clearInterval(callTimerRef.current)
      callTimerRef.current = null
    }

    // Stop all audio playback
    stopAllPlayback()

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
    }

    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }

    if (audioContextRef.current) {
      audioContextRef.current.close()
      audioContextRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setIsMicActive(false)
    setIsConnected(false)
    setCallStatus('idle')  // Reset to idle

    fetchTranscripts()
  }

  // Toggle call
  const toggleCall = () => {
    if (callStatus === 'active' || callStatus === 'connecting') {
      stopCall()
    } else {
      setCallDuration(0)
      startCall()
    }
  }

  // Initial fetch
  useEffect(() => {
    fetchSettings()
    fetchTranscripts()
  }, [])

  // Format duration
  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Get button text based on status
  const getButtonText = () => {
    switch (callStatus) {
      case 'connecting': return '⏳ Connecting...'
      case 'active': return '🔴 End Call'
      default: return '🎤 Start Call'
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <h1>🎙️ Anvenssa Voice Agent</h1>
          <div className={`connection-status ${isConnected ? 'online' : 'offline'}`}>
            <span className="status-dot"></span>
            {isConnected ? 'Connected' : 'Offline'}
          </div>
        </div>
      </header>

      <div className="container">
        {/* Call Section - Left Side */}
        <section className="call-card">
          <div className="call-content">
            <button
              className={`call-btn ${callStatus === 'active' ? 'active' : ''} ${callStatus === 'connecting' ? 'connecting' : ''}`}
              onClick={toggleCall}
              disabled={callStatus === 'connecting'}
            >
              <span className="btn-icon">{callStatus === 'active' ? '📞' : '🎤'}</span>
              <span className="btn-text">{getButtonText()}</span>
            </button>

            {callStatus === 'active' && (
              <div className="call-info">
                <div className="timer">{formatDuration(callDuration)}</div>
                {isMicActive && <div className="mic-status"><span className="pulse-dot"></span> Listening...</div>}
              </div>
            )}
          </div>
        </section>

        {/* Settings Panel - Right Top */}
        <section className="panel settings-panel">
          <h2>⚙️ Settings</h2>
          <div className="setting-row">
            <label>Max Duration (seconds)</label>
            <input
              type="number"
              value={localSettings.max_call_duration}
              onChange={(e) => setLocalSettings({ ...localSettings, max_call_duration: parseInt(e.target.value) || 600 })}
              min="60"
              max="3600"
            />
          </div>
          <div className="setting-row">
            <label>Silence Timeout (seconds)</label>
            <input
              type="number"
              value={localSettings.max_silence_duration}
              onChange={(e) => setLocalSettings({ ...localSettings, max_silence_duration: parseInt(e.target.value) || 20 })}
              min="5"
              max="120"
            />
          </div>
          <button className="save-btn" onClick={saveSettings}>
            💾 Save Settings
          </button>
        </section>

        {/* Logs Panel - Right Bottom */}
        <section className="panel logs-panel">
          <h2>📋 Activity Log</h2>
          <div className="logs-list">
            {logs.length === 0 ? (
              <div className="no-logs">No activity yet...</div>
            ) : (
              logs.map((log, i) => (
                <div key={i} className="log-item">{log}</div>
              ))
            )}
          </div>
        </section>

        {/* Transcripts Panel - Bottom Full Width */}
        <section className="panel transcripts-panel">
          <div className="panel-header">
            <h2>📝 Transcripts</h2>
            <button className="icon-btn" onClick={fetchTranscripts}>🔄</button>
          </div>
          <div className="transcripts-grid">
            {savedTranscripts.length === 0 ? (
              <div className="no-transcripts">No transcripts yet</div>
            ) : (
              savedTranscripts.slice(0, 8).map((t, i) => (
                <div key={i} className="transcript-card" onClick={() => viewTranscript(t.filename)}>
                  <div className="transcript-name">📄 {t.filename}</div>
                  <div className="transcript-date">{new Date(t.created).toLocaleString()}</div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* Transcript Modal */}
      {selectedTranscript && (
        <div className="modal-overlay" onClick={() => setSelectedTranscript(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📄 {selectedTranscript.filename}</h3>
              <button className="close-btn" onClick={() => setSelectedTranscript(null)}>✕</button>
            </div>
            <pre className="modal-body">{selectedTranscript.content}</pre>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
