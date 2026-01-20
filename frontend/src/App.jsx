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

    // Agent Configuration State
    const [activeView, setActiveView] = useState('home') // home, agent
    const [agentConfig, setAgentConfig] = useState({
        speech_settings: {
            recognition_language: 'en-IN',
            synthesis_voice_name: 'en-IN-NeerjaNeural'
        },
        system_prompt: '',
        active_knowledge_base_id: null,
        knowledge_bases: [],
        prompt_variables: {},
        detected_variables: []
    })
    const [availableVoices, setAvailableVoices] = useState([])
    const [availableLanguages, setAvailableLanguages] = useState([])
    const [uploadingKB, setUploadingKB] = useState(false)
    const [newKBName, setNewKBName] = useState('')
    const [selectedFile, setSelectedFile] = useState(null)
    const [editingPrompt, setEditingPrompt] = useState('')
    const [savingPrompt, setSavingPrompt] = useState(false)
    // Template Variables State
    const [promptVariables, setPromptVariables] = useState({})
    const [detectedVariables, setDetectedVariables] = useState([])
    const [savingVariables, setSavingVariables] = useState(false)
    const fileInputRef = useRef(null)
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
    // Fetch calls list from database
    const fetchTranscripts = async () => {
        try {
            const res = await fetch(`${API_URL}/api/calls`)
            const data = await res.json()
            setSavedTranscripts(data.calls || [])
        } catch (err) {
            addLog(`Error fetching calls: ${err.message}`)
        }
    }
    // View call transcript
    const viewTranscript = async (callId) => {
        try {
            const res = await fetch(`${API_URL}/api/calls/${callId}`)
            const data = await res.json()
            setSelectedTranscript({
                filename: `Call ${callId.substring(0, 8)}...`,
                content: data.transcript || 'No transcript available'
            })
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
        fetchAgentConfig()
        fetchVoices()
    }, [])

    // Fetch agent configuration
    const fetchAgentConfig = async () => {
        try {
            const res = await fetch(`${API_URL}/api/agent/config`)
            const data = await res.json()
            setAgentConfig(data)
            setEditingPrompt(data.system_prompt || '')
            setPromptVariables(data.prompt_variables || {})
            setDetectedVariables(data.detected_variables || [])
        } catch (err) {
            addLog(`Error fetching agent config: ${err.message}`)
        }
    }

    // Fetch available voices
    const fetchVoices = async () => {
        try {
            const res = await fetch(`${API_URL}/api/agent/voices`)
            const data = await res.json()
            setAvailableVoices(data.voices || [])
            setAvailableLanguages(data.languages || [])
        } catch (err) {
            console.error('Error fetching voices:', err)
        }
    }

    // Update speech settings
    const updateSpeechSettings = async (recognition_language, synthesis_voice_name) => {
        try {
            const res = await fetch(`${API_URL}/api/agent/speech`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ recognition_language, synthesis_voice_name })
            })
            const data = await res.json()
            setAgentConfig(prev => ({
                ...prev,
                speech_settings: data
            }))
            addLog(`✅ Speech settings updated: ${recognition_language}, ${synthesis_voice_name}`)
        } catch (err) {
            addLog(`Error updating speech settings: ${err.message}`)
        }
    }

    // Upload knowledge base
    const uploadKnowledgeBase = async () => {
        if (!selectedFile || !newKBName.trim()) {
            addLog('Please select a file and enter a name')
            return
        }

        setUploadingKB(true)
        try {
            const formData = new FormData()
            formData.append('file', selectedFile)
            formData.append('name', newKBName.trim())

            const res = await fetch(`${API_URL}/api/agent/knowledge-bases`, {
                method: 'POST',
                body: formData
            })
            const data = await res.json()

            if (data.error) {
                addLog(`❌ Upload failed: ${data.error}`)
            } else {
                addLog(`✅ Knowledge base "${newKBName}" created with ${data.knowledge_base.chunk_count} chunks`)
                setNewKBName('')
                setSelectedFile(null)
                if (fileInputRef.current) fileInputRef.current.value = ''
                fetchAgentConfig()
            }
        } catch (err) {
            addLog(`Error uploading: ${err.message}`)
        } finally {
            setUploadingKB(false)
        }
    }

    // Activate knowledge base
    const activateKnowledgeBase = async (kbId) => {
        try {
            const res = await fetch(`${API_URL}/api/agent/knowledge-bases/${kbId}/activate`, {
                method: 'POST'
            })
            const data = await res.json()
            if (data.success) {
                setAgentConfig(prev => ({
                    ...prev,
                    active_knowledge_base_id: kbId
                }))
                addLog(`✅ Knowledge base activated`)
            }
        } catch (err) {
            addLog(`Error activating KB: ${err.message}`)
        }
    }

    // Deactivate knowledge base (use default)
    const deactivateKnowledgeBase = async () => {
        try {
            const res = await fetch(`${API_URL}/api/agent/knowledge-bases/deactivate`, {
                method: 'POST'
            })
            const data = await res.json()
            if (data.success) {
                setAgentConfig(prev => ({
                    ...prev,
                    active_knowledge_base_id: null
                }))
                addLog(`✅ Using default knowledge base`)
            }
        } catch (err) {
            addLog(`Error: ${err.message}`)
        }
    }

    // Delete knowledge base
    const deleteKnowledgeBase = async (kbId) => {
        if (!confirm('Are you sure you want to delete this knowledge base?')) return

        try {
            const res = await fetch(`${API_URL}/api/agent/knowledge-bases/${kbId}`, {
                method: 'DELETE'
            })
            const data = await res.json()
            if (data.success) {
                addLog(`✅ Knowledge base deleted`)
                fetchAgentConfig()
            }
        } catch (err) {
            addLog(`Error deleting KB: ${err.message}`)
        }
    }

    // Extract variables from prompt text (client-side)
    const extractVariablesFromPrompt = (prompt) => {
        const pattern = /\{(\w+)\}/g
        const matches = [...prompt.matchAll(pattern)]
        const unique = [...new Set(matches.map(m => m[1]))]
        return unique
    }

    // Update detected variables when prompt changes
    useEffect(() => {
        const detected = extractVariablesFromPrompt(editingPrompt)
        setDetectedVariables(detected)
    }, [editingPrompt])

    // Update system prompt
    const updateSystemPrompt = async () => {
        if (!editingPrompt.trim()) {
            addLog('System prompt cannot be empty')
            return
        }

        setSavingPrompt(true)
        try {
            const res = await fetch(`${API_URL}/api/agent/system-prompt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ system_prompt: editingPrompt })
            })
            const data = await res.json()
            setAgentConfig(prev => ({
                ...prev,
                system_prompt: data.system_prompt
            }))
            // Re-fetch to get updated detected variables
            const configRes = await fetch(`${API_URL}/api/agent/config`)
            const configData = await configRes.json()
            setDetectedVariables(configData.detected_variables || [])
            addLog(`✅ System prompt updated`)
        } catch (err) {
            addLog(`Error updating system prompt: ${err.message}`)
        } finally {
            setSavingPrompt(false)
        }
    }

    // Reset system prompt to default
    const resetSystemPrompt = async () => {
        if (!confirm('Reset system prompt to default?')) return

        setSavingPrompt(true)
        try {
            const res = await fetch(`${API_URL}/api/agent/system-prompt/reset`, {
                method: 'POST'
            })
            const data = await res.json()
            setAgentConfig(prev => ({
                ...prev,
                system_prompt: data.system_prompt
            }))
            setEditingPrompt(data.system_prompt)
            setPromptVariables({})
            setDetectedVariables(data.detected_variables || [])
            addLog(`✅ System prompt reset to default`)
        } catch (err) {
            addLog(`Error resetting system prompt: ${err.message}`)
        } finally {
            setSavingPrompt(false)
        }
    }

    // Save prompt variables
    const savePromptVariables = async () => {
        setSavingVariables(true)
        try {
            const res = await fetch(`${API_URL}/api/agent/prompt-variables`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ variables: promptVariables })
            })
            const data = await res.json()
            setPromptVariables(data.variables || {})
            addLog(`✅ Template variables saved`)
        } catch (err) {
            addLog(`Error saving variables: ${err.message}`)
        } finally {
            setSavingVariables(false)
        }
    }

    // Update a single variable value
    const updateVariableValue = (varName, value) => {
        setPromptVariables(prev => ({
            ...prev,
            [varName]: value
        }))
    }

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
            {/* Sidebar */}
            <aside className="sidebar">
                <div className="sidebar-header">
                    <div className="sidebar-logo">🎙️ Anvenssa</div>
                </div>
                <nav className="sidebar-nav">
                    <div className="nav-section">
                        <div
                            className={`nav-item ${activeView === 'home' ? 'active' : ''}`}
                            onClick={() => setActiveView('home')}
                        >
                            <span className="nav-icon">🏠</span>
                            <span>Home</span>
                        </div>
                    </div>
                    <div className="nav-section">
                        <div className="nav-section-title">Dashboard</div>
                        <div
                            className={`nav-item ${activeView === 'agent' ? 'active' : ''}`}
                            onClick={() => setActiveView('agent')}
                        >
                            <span className="nav-icon">🤖</span>
                            <span>Agent</span>
                        </div>
                        <div className="nav-item">
                            <span className="nav-icon">📞</span>
                            <span>Calls</span>
                        </div>
                        <div className="nav-item">
                            <span className="nav-icon">📊</span>
                            <span>Analytics</span>
                        </div>
                        <div className="nav-item">
                            <span className="nav-icon">⚙️</span>
                            <span>Settings</span>
                        </div>
                    </div>
                    <div className="nav-section">
                        <div className="nav-section-title">Resources</div>
                        <div className="nav-item">
                            <span className="nav-icon">📚</span>
                            <span>Documentation</span>
                        </div>
                    </div>
                </nav>
                <div className="sidebar-footer">
                    <div className="connection-badge">
                        <span className={`status-dot ${isConnected ? 'online' : 'offline'}`}></span>
                        <span>{isConnected ? 'Connected' : 'Offline'}</span>
                    </div>
                </div>
            </aside>
            {/* Main Content */}
            <main className="main-content">
                {/* Header */}
                <header className="header">
                    <div className="header-content">
                        <h1 className="welcome-text">{activeView === 'home' ? 'Welcome back, User' : 'Agent Configuration'}</h1>
                        <div className="header-actions">
                            <button className="header-btn" onClick={() => { fetchTranscripts(); fetchAgentConfig(); }}>
                                🔄 Refresh
                            </button>
                        </div>
                    </div>
                </header>
                {/* Content Area */}
                <div className="content-area">
                    {activeView === 'agent' ? (
                        /* Agent Configuration View */
                        <>
                            {/* Speech Settings Section */}
                            <section className="section">
                                <h2 className="section-title">Voice & Language Settings</h2>
                                <div className="cards-grid">
                                    {/* Recognition Language Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon settings">🗣️</div>
                                            <div>
                                                <div className="card-title">Recognition Language</div>
                                                <div className="card-description">Language for speech-to-text</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="setting-row">
                                                <label>Select Language</label>
                                                <select
                                                    value={agentConfig.speech_settings.recognition_language}
                                                    onChange={(e) => updateSpeechSettings(e.target.value, agentConfig.speech_settings.synthesis_voice_name)}
                                                    className="setting-select"
                                                >
                                                    {availableLanguages.map(lang => (
                                                        <option key={lang.id} value={lang.id}>{lang.name}</option>
                                                    ))}
                                                </select>
                                            </div>
                                            <div className="current-value">
                                                Current: <strong>{agentConfig.speech_settings.recognition_language}</strong>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Voice Selection Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon logs">🔊</div>
                                            <div>
                                                <div className="card-title">Synthesis Voice</div>
                                                <div className="card-description">Voice for text-to-speech</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="setting-row">
                                                <label>Select Voice</label>
                                                <select
                                                    value={agentConfig.speech_settings.synthesis_voice_name}
                                                    onChange={(e) => updateSpeechSettings(agentConfig.speech_settings.recognition_language, e.target.value)}
                                                    className="setting-select"
                                                >
                                                    {availableVoices.map(voice => (
                                                        <option key={voice.id} value={voice.id}>{voice.name}</option>
                                                    ))}
                                                </select>
                                            </div>
                                            <div className="current-value">
                                                Current: <strong>{agentConfig.speech_settings.synthesis_voice_name}</strong>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </section>

                            {/* System Prompt Section */}
                            <section className="section">
                                <h2 className="section-title">System Prompt</h2>
                                <div className="card">
                                    <div className="card-header">
                                        <div className="card-icon settings">📝</div>
                                        <div>
                                            <div className="card-title">Agent Behavior</div>
                                            <div className="card-description">Define how the AI agent responds to users</div>
                                        </div>
                                    </div>
                                    <div className="card-content">
                                        <div className="setting-row">
                                            <label>System Prompt</label>
                                            <textarea
                                                value={editingPrompt}
                                                onChange={(e) => setEditingPrompt(e.target.value)}
                                                placeholder="Enter the system prompt for the AI agent..."
                                                className="prompt-textarea"
                                                rows={10}
                                            />
                                        </div>
                                        <div className="prompt-actions">
                                            <button
                                                className="save-btn"
                                                onClick={updateSystemPrompt}
                                                disabled={savingPrompt || !editingPrompt.trim()}
                                            >
                                                {savingPrompt ? '⏳ Saving...' : '💾 Save Prompt'}
                                            </button>
                                            <button
                                                className="save-btn secondary"
                                                onClick={resetSystemPrompt}
                                                disabled={savingPrompt}
                                            >
                                                🔄 Reset to Default
                                            </button>
                                        </div>
                                        <div className="prompt-hint">
                                            💡 Tip: Use {'{variable_name}'} syntax to create dynamic variables. Example: {"Your name is {agent_name}"}
                                        </div>
                                    </div>
                                </div>

                                {/* Template Variables Section - Only show if variables detected */}
                                {detectedVariables.length > 0 && (
                                    <div className="card template-variables-card">
                                        <div className="card-header">
                                            <div className="card-icon variables">📋</div>
                                            <div>
                                                <div className="card-title">Template Variables ({detectedVariables.length} detected)</div>
                                                <div className="card-description">Set values for dynamic placeholders in your prompt</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="variables-grid">
                                                {detectedVariables.map(varName => (
                                                    <div key={varName} className="variable-row">
                                                        <label className="variable-label">
                                                            <span className="variable-name">{'{' + varName + '}'}</span>
                                                        </label>
                                                        <input
                                                            type="text"
                                                            value={promptVariables[varName] || ''}
                                                            onChange={(e) => updateVariableValue(varName, e.target.value)}
                                                            placeholder={`Enter value for ${varName}`}
                                                            className="variable-input"
                                                        />
                                                    </div>
                                                ))}
                                            </div>
                                            <div className="prompt-actions">
                                                <button
                                                    className="save-btn"
                                                    onClick={savePromptVariables}
                                                    disabled={savingVariables}
                                                >
                                                    {savingVariables ? '⏳ Saving...' : '💾 Save Variables'}
                                                </button>
                                            </div>
                                            <div className="prompt-hint">
                                                💡 These values will be automatically injected into the system prompt during calls.
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </section>

                            {/* Knowledge Base Section */}
                            <section className="section">
                                <h2 className="section-title">Knowledge Base</h2>
                                <div className="cards-grid">
                                    {/* Upload New KB Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon history">📄</div>
                                            <div>
                                                <div className="card-title">Upload Knowledge Base</div>
                                                <div className="card-description">Add PDF or TXT files</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="setting-row">
                                                <label>Knowledge Base Name</label>
                                                <input
                                                    type="text"
                                                    value={newKBName}
                                                    onChange={(e) => setNewKBName(e.target.value)}
                                                    placeholder="e.g., Product Guide"
                                                />
                                            </div>
                                            <div className="setting-row">
                                                <label>Select File (PDF, TXT, MD)</label>
                                                <input
                                                    type="file"
                                                    ref={fileInputRef}
                                                    accept=".pdf,.txt,.md"
                                                    onChange={(e) => setSelectedFile(e.target.files[0])}
                                                    className="file-input"
                                                />
                                            </div>
                                            {selectedFile && (
                                                <div className="selected-file">
                                                    📎 {selectedFile.name}
                                                </div>
                                            )}
                                            <button
                                                className="save-btn"
                                                onClick={uploadKnowledgeBase}
                                                disabled={uploadingKB || !selectedFile || !newKBName.trim()}
                                            >
                                                {uploadingKB ? '⏳ Uploading...' : '📤 Upload & Create'}
                                            </button>
                                        </div>
                                    </div>

                                    {/* Active KB Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon call">📚</div>
                                            <div>
                                                <div className="card-title">Active Knowledge Base</div>
                                                <div className="card-description">Currently used for responses</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            {agentConfig.active_knowledge_base_id ? (
                                                <>
                                                    {agentConfig.knowledge_bases
                                                        .filter(kb => kb.id === agentConfig.active_knowledge_base_id)
                                                        .map(kb => (
                                                            <div key={kb.id} className="active-kb-info">
                                                                <div className="kb-name">📖 {kb.name}</div>
                                                                <div className="kb-meta">{kb.chunk_count} chunks • {kb.filename}</div>
                                                            </div>
                                                        ))
                                                    }
                                                    <button className="save-btn secondary" onClick={deactivateKnowledgeBase}>
                                                        🔄 Use Default KB
                                                    </button>
                                                </>
                                            ) : (
                                                <div className="no-active-kb">
                                                    <div className="kb-name">📖 Default Knowledge Base</div>
                                                    <div className="kb-meta">Built-in Anvenssa knowledge</div>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </section>

                            {/* Knowledge Base List */}
                            <section className="section">
                                <h2 className="section-title">Your Knowledge Bases</h2>
                                <div className="card">
                                    <div className="card-content">
                                        {agentConfig.knowledge_bases.length === 0 ? (
                                            <div className="no-logs">No custom knowledge bases yet. Upload one above!</div>
                                        ) : (
                                            <div className="kb-list">
                                                {agentConfig.knowledge_bases.map(kb => (
                                                    <div key={kb.id} className={`kb-item ${kb.id === agentConfig.active_knowledge_base_id ? 'active' : ''}`}>
                                                        <div className="kb-item-info">
                                                            <div className="kb-item-name">
                                                                {kb.id === agentConfig.active_knowledge_base_id && <span className="active-badge">✓</span>}
                                                                {kb.name}
                                                            </div>
                                                            <div className="kb-item-meta">
                                                                {kb.chunk_count} chunks • {kb.filename} • {new Date(kb.created_at).toLocaleDateString()}
                                                            </div>
                                                        </div>
                                                        <div className="kb-item-actions">
                                                            {kb.id !== agentConfig.active_knowledge_base_id && (
                                                                <button
                                                                    className="kb-action-btn activate"
                                                                    onClick={() => activateKnowledgeBase(kb.id)}
                                                                >
                                                                    Activate
                                                                </button>
                                                            )}
                                                            <button
                                                                className="kb-action-btn delete"
                                                                onClick={() => deleteKnowledgeBase(kb.id)}
                                                            >
                                                                Delete
                                                            </button>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </section>
                        </>
                    ) : (
                        /* Home View */
                        <>
                            {/* Main Cards Section */}
                            <section className="section">
                                <h2 className="section-title">Voice Agent</h2>
                                <div className="cards-grid">
                                    {/* Call Card */}
                                    <div className="card call-card">
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
                                        {callStatus === 'idle' && (
                                            <div className="card-description" style={{ marginTop: '16px', textAlign: 'center' }}>
                                                Click to start a voice conversation with the AI agent
                                            </div>
                                        )}
                                    </div>
                                    {/* Settings Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon settings">⚙️</div>
                                            <div>
                                                <div className="card-title">Call Settings</div>
                                                <div className="card-description">Configure call parameters</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
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
                                                Save Settings
                                            </button>
                                        </div>
                                    </div>
                                    {/* Activity Log Card */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon logs">📋</div>
                                            <div>
                                                <div className="card-title">Activity Log</div>
                                                <div className="card-description">Real-time call events</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="logs-list">
                                                {logs.length === 0 ? (
                                                    <div className="no-logs">No activity yet...</div>
                                                ) : (
                                                    <div>
                                                        {[...logs].reverse().map((log, i) => (
                                                            <div key={i} className="log-item">{log}</div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </section>
                            {/* Call History Section */}
                            <section className="section">
                                <h2 className="section-title">Call History</h2>
                                <div className="card">
                                    <div className="card-header">
                                        <div className="card-icon history">📝</div>
                                        <div>
                                            <div className="card-title">Recent Calls</div>
                                            <div className="card-description">View transcripts from previous conversations</div>
                                        </div>
                                    </div>
                                    <div className="card-content">
                                        {savedTranscripts.length === 0 ? (
                                            <div className="no-logs">No calls recorded yet</div>
                                        ) : (
                                            <div className="history-grid">
                                                {savedTranscripts.slice(0, 8).map((call, i) => (
                                                    <div key={i} className="history-item" onClick={() => viewTranscript(call.id)}>
                                                        <div className="history-id">📞 {call.id.substring(0, 8)}...</div>
                                                        <div className="history-meta">
                                                            {call.start_time ? new Date(call.start_time).toLocaleString() : 'Unknown'}
                                                            {call.duration && ` • ${call.duration}s`}
                                                        </div>
                                                        {call.end_reason && <div className="history-reason">{call.end_reason}</div>}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </section>
                            {/* Quick Actions */}
                            <div className="quick-actions">
                                <div className="quick-action" onClick={() => setActiveView('agent')}>
                                    <div className="quick-action-icon">🤖</div>
                                    <div className="quick-action-title">Agent Config</div>
                                    <div className="quick-action-desc">Voice & Knowledge</div>
                                </div>
                                <div className="quick-action">
                                    <div className="quick-action-icon">📊</div>
                                    <div className="quick-action-title">Analytics</div>
                                    <div className="quick-action-desc">View call statistics</div>
                                </div>
                                <div className="quick-action">
                                    <div className="quick-action-icon">✅</div>
                                    <div className="quick-action-title">Status</div>
                                    <div className="quick-action-desc">{isConnected ? 'System Online' : 'System Offline'}</div>
                                </div>
                                <div className="quick-action">
                                    <div className="quick-action-icon">❓</div>
                                    <div className="quick-action-title">Help Center</div>
                                    <div className="quick-action-desc">Get support</div>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </main>
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
