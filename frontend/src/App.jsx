import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import { useAuth } from './auth/AuthContext.jsx'
import AgentList from './components/AgentList.jsx'
import AgentConfig from './components/AgentConfig.jsx'

// const API_URL = 'https://voice.anvenssa.com'
// const WS_URL = 'wss://voice.anvenssa.com/ws/audio'
const API_URL = 'http://localhost:8000'
const WS_URL = 'ws://localhost:8000/ws/audio'

function App() {

    // Authentication
    const { user, logout } = useAuth();

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

    // Navigation State
    const [activeView, setActiveView] = useState('home') // home, agents, agent-config, call-history

    // Agent Management State
    const [selectedAgentId, setSelectedAgentId] = useState(null)
    const [agents, setAgents] = useState([])  // List of all agents
    const [selectedTestAgentId, setSelectedTestAgentId] = useState('')  // Agent selected for browser testing

    // FreJun Phone Call State
    const [phoneNumber, setPhoneNumber] = useState('')
    const [phoneCallStatus, setPhoneCallStatus] = useState('idle') // idle, calling, active, ended
    const [phoneCallId, setPhoneCallId] = useState(null)
    const [frejunConfig, setFrejunConfig] = useState({ configured: false, from_number: null })

    // Call History State
    const [callHistory, setCallHistory] = useState([])
    const [loadingHistory, setLoadingHistory] = useState(false)
    const [playingRecordingId, setPlayingRecordingId] = useState(null)
    const [statusFilter, setStatusFilter] = useState('all')
    const [dateFilter, setDateFilter] = useState('')
    const audioPlayerRef = useRef(null)

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
            if (res.ok) {
                const data = await res.json()
                setSettings(data)
                setLocalSettings(data)
            }
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

    // Fetch calls list from database (Legacy - for Home view)
    const fetchTranscripts = async () => {
        try {
            const res = await fetch(`${API_URL}/api/calls`)
            if (res.ok) {
                const data = await res.json()
                setSavedTranscripts(data.calls || [])
            }
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
        // ... (unchanged playback logic)
        stopPlaybackRef.current = true
        if (currentSourceRef.current) {
            try {
                currentSourceRef.current.stop()
                currentSourceRef.current.disconnect()
            } catch (e) { }
            currentSourceRef.current = null
        }
        playbackQueueRef.current = []
        isPlayingRef.current = false
        if (playbackContextRef.current && playbackContextRef.current.state !== 'closed') {
            try {
                playbackContextRef.current.close()
            } catch (e) { }
            playbackContextRef.current = null
        }
    }

    // Play audio chunk
    const playAudioChunk = (base64Data) => {
        return new Promise((resolve, reject) => {
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
            if (pendingPlaybackCompleteRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
                pendingPlaybackCompleteRef.current = false
                wsRef.current.send(JSON.stringify({ type: 'playback_complete' }))
                addLog('🔈 All audio played - silence timer started')
            }
            return
        }
        isPlayingRef.current = true
        stopPlaybackRef.current = false
        while (playbackQueueRef.current.length > 0 && !stopPlaybackRef.current) {
            const chunk = playbackQueueRef.current.shift()
            try {
                await playAudioChunk(chunk)
            } catch (err) {
                if (stopPlaybackRef.current) break
                console.error('Playback error:', err)
            }
        }
        isPlayingRef.current = false
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
            // Pass agent_id in WebSocket URL for multi-tenant support
            const wsUrl = selectedTestAgentId
                ? `${WS_URL}?agent_id=${selectedTestAgentId}`
                : WS_URL
            const selectedAgent = agents.find(a => a.id === selectedTestAgentId)
            if (selectedAgent) {
                addLog(`🤖 Using agent: ${selectedAgent.name}`)
            }
            const ws = new WebSocket(wsUrl)
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
                    if (data.first_chunk) {
                        stopAllPlayback()
                        pendingPlaybackCompleteRef.current = false
                        addLog('🔄 New response starting...')
                    }
                    playbackQueueRef.current.push(data.data)
                    processPlaybackQueue()
                } else if (data.type === 'audio_end') {
                    addLog('🔊 Agent response received, playing audio...')
                    pendingPlaybackCompleteRef.current = true
                    processPlaybackQueue()
                } else if (data.type === 'call_end') {
                    addLog(`📞 Call ended: ${data.reason}`)
                    stopCall()
                } else if (data.type === 'barge_in') {
                    stopAllPlayback()
                    pendingPlaybackCompleteRef.current = false
                    addLog('🔴 Interrupting - new query detected...')
                }
            }
            ws.onclose = () => {
                addLog('🔴 Disconnected from server')
                setIsConnected(false)
                setIsMicActive(false)
                setCallStatus('idle')
            }
            ws.onerror = (err) => {
                addLog(`❌ Connection error`)
                setCallStatus('idle')
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
        setCallStatus('idle')
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
        fetchFrejunConfig()
        fetchAgentsList()
    }, [])

    // Fetch agents list for browser testing selector
    // MULTI-TENANT: Filter by user's organization
    const fetchAgentsList = async () => {
        try {
            // Build URL with organization filter if user has one
            let url = `${API_URL}/api/agents`
            if (user?.organizationId) {
                url += `?organization_id=${user.organizationId}`
            }

            const res = await fetch(url)
            if (res.ok) {
                const data = await res.json()
                setAgents(data.agents || [])
                // Auto-select first agent if available
                if (data.agents && data.agents.length > 0 && !selectedTestAgentId) {
                    setSelectedTestAgentId(data.agents[0].id)
                }
            }
        } catch (err) {
            console.error('Error fetching agents:', err)
        }
    }

    // Fetch FreJun configuration
    const fetchFrejunConfig = async () => {
        try {
            const res = await fetch(`${API_URL}/api/frejun/config`)
            if (res.ok) {
                const data = await res.json()
                setFrejunConfig(data)
            }
        } catch (err) {
            console.error('Error fetching FreJun config:', err)
        }
    }

    // Initiate phone call via FreJun
    const initiatePhoneCall = async () => {
        if (!phoneNumber.trim()) {
            addLog('Please enter a phone number')
            return
        }
        setPhoneCallStatus('calling')
        addLog(`📞 Initiating call to ${phoneNumber}...`)
        try {
            const res = await fetch(`${API_URL}/api/frejun/initiate-call`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ to_number: phoneNumber, record: true })
            })
            const data = await res.json()
            if (data.success) {
                setPhoneCallId(data.call_id)
                setPhoneCallStatus('active')
                addLog(`✅ ${data.message}`)
                addLog(`📞 Call ID: ${data.call_id}`)
            } else {
                setPhoneCallStatus('idle')
                addLog(`❌ Call failed: ${data.message}`)
            }
        } catch (err) {
            setPhoneCallStatus('idle')
            addLog(`❌ Error: ${err.message}`)
        }
    }

    const resetPhoneCall = () => {
        setPhoneCallStatus('idle')
        setPhoneCallId(null)
        setPhoneNumber('')
    }

    // ============================================
    // Call History Functions
    // ============================================

    // MULTI-TENANT: Filter call history by user's organization
    const fetchCallHistory = async () => {
        setLoadingHistory(true)
        try {
            // Build URL with organization filter if user has one
            let url = `${API_URL}/api/calls/history`
            if (user?.organizationId) {
                url += `?organization_id=${user.organizationId}`
            }

            const res = await fetch(url)
            const data = await res.json()
            setCallHistory(data.calls || [])
        } catch (err) {
            addLog(`Error fetching call history: ${err.message}`)
        } finally {
            setLoadingHistory(false)
        }
    }

    const playRecording = (call) => {
        if (!call.recording_url) {
            addLog('No recording available for this call')
            return
        }
        if (playingRecordingId === call.id) {
            if (audioPlayerRef.current) {
                audioPlayerRef.current.pause()
                audioPlayerRef.current.currentTime = 0
            }
            setPlayingRecordingId(null)
        } else {
            if (audioPlayerRef.current) {
                audioPlayerRef.current.pause()
            }
            const proxyUrl = `${API_URL}/api/calls/${call.id}/recording`
            audioPlayerRef.current = new Audio(proxyUrl)
            audioPlayerRef.current.onended = () => {
                setPlayingRecordingId(null)
                addLog('Recording playback finished')
            }
            audioPlayerRef.current.onerror = (e) => {
                console.error('Audio playback error:', e)
                addLog('Error playing recording - recording may not be available yet')
                setPlayingRecordingId(null)
            }
            audioPlayerRef.current.onloadstart = () => {
                addLog('Loading recording...')
            }
            audioPlayerRef.current.oncanplay = () => {
                addLog('Playing recording...')
            }
            audioPlayerRef.current.play().catch(err => {
                addLog(`Error: ${err.message}`)
                setPlayingRecordingId(null)
            })
            setPlayingRecordingId(call.id)
        }
    }

    const getFilteredCallHistory = () => {
        return callHistory.filter(call => {
            if (statusFilter !== 'all' && call.status !== statusFilter) return false
            if (dateFilter) {
                const callDate = new Date(call.start_time || call.created_at).toISOString().split('T')[0]
                if (callDate !== dateFilter) return false
            }
            return true
        })
    }

    const getStatusBadgeClass = (status) => {
        switch (status) {
            case 'completed': return 'status-badge completed'
            case 'initiated': return 'status-badge initiated'
            case 'streaming': return 'status-badge streaming'
            case 'answered': return 'status-badge answered'
            case 'failed': return 'status-badge failed'
            case 'recording_failed': return 'status-badge failed'
            default: return 'status-badge'
        }
    }

    const formatDateTime = (dateStr) => {
        if (!dateStr) return 'Unknown'
        const utcDateStr = dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`;
        const date = new Date(utcDateStr)
        return date.toLocaleString('en-IN', {
            timeZone: 'Asia/Kolkata',
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit', hour12: true
        })
    }

    const formatDuration = (seconds) => {
        const mins = Math.floor(seconds / 60)
        const secs = seconds % 60
        return `${mins}:${secs.toString().padStart(2, '0')}`
    }

    const getButtonText = () => {
        switch (callStatus) {
            case 'connecting': return '⏳ Connecting...'
            case 'active': return '🔴 End Call'
            default: return '🎤 Start Call'
        }
    }

    // ============================================
    // Agent Functions
    // ============================================
    const handleEditAgent = (agent) => {
        setSelectedAgentId(agent.id)
        setActiveView('agent-config')
    }

    const handleCreateAgent = () => {
        setSelectedAgentId(null)
        setActiveView('agent-config')
    }

    const handleSaveAgent = () => {
        setActiveView('agents')
        addLog('Agent saved successfully')
    }

    const handleCancelAgent = () => {
        setActiveView('agents')
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
                            className={`nav-item ${activeView === 'agents' || activeView === 'agent-config' ? 'active' : ''}`}
                            onClick={() => setActiveView('agents')}
                        >
                            <span className="nav-icon">🤖</span>
                            <span>Agents</span>
                        </div>
                        <div
                            className={`nav-item ${activeView === 'call-history' ? 'active' : ''}`}
                            onClick={() => { setActiveView('call-history'); fetchCallHistory(); }}
                        >
                            <span className="nav-icon">📞</span>
                            <span>Call History</span>
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
                        <h1 className="welcome-text">
                            {activeView === 'home' ? `Welcome back, ${user?.displayName || 'User'}` :
                                activeView === 'agents' ? 'Agents' :
                                    activeView === 'agent-config' ? (selectedAgentId ? 'Edit Agent' : 'New Agent') :
                                        activeView === 'call-history' ? 'Recent Call History' :
                                            'Dashboard'}
                        </h1>
                        <div className="header-actions">
                            <button className="header-btn" onClick={() => {
                                fetchTranscripts();
                                if (activeView === 'call-history') fetchCallHistory();
                            }}>
                                🔄 Refresh
                            </button>
                            <div className="user-menu">
                                <span className="user-badge">
                                    <span className="user-avatar">👤</span>
                                    <span className="user-name">{user?.displayName}</span>
                                </span>
                                <button className="header-btn logout-btn" onClick={logout}>
                                    🚪 Logout
                                </button>
                            </div>
                        </div>
                    </div>
                </header>
                {/* Content Area */}
                <div className="content-area">
                    {/* View Switching */}
                    {activeView === 'home' && (
                        <>
                            {/* Home/Default View Reused */}
                            <section className="section">
                                <h2 className="section-title">Voice Agent Demo</h2>
                                <div className="cards-grid">
                                    <div className="card call-card">
                                        {/* Agent Selector for Browser Testing */}
                                        {agents.length > 0 && callStatus === 'idle' && (
                                            <div className="agent-selector" style={{ marginBottom: '16px', textAlign: 'center' }}>
                                                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', color: '#888' }}>
                                                    Select Agent to Test
                                                </label>
                                                <select
                                                    value={selectedTestAgentId}
                                                    onChange={(e) => setSelectedTestAgentId(e.target.value)}
                                                    style={{
                                                        padding: '8px 16px',
                                                        borderRadius: '8px',
                                                        border: '1px solid #444',
                                                        background: '#2a2a2a',
                                                        color: '#fff',
                                                        fontSize: '14px',
                                                        minWidth: '200px',
                                                        cursor: 'pointer'
                                                    }}
                                                >
                                                    <option value="">-- Default Agent --</option>
                                                    {agents.map(agent => (
                                                        <option key={agent.id} value={agent.id}>
                                                            {agent.name}
                                                        </option>
                                                    ))}
                                                </select>
                                            </div>
                                        )}
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
                                                Click to start a browser-based demo call
                                            </div>
                                        )}
                                    </div>
                                    {/* Phone Call Card */}
                                    <div className="card phone-call-card">
                                        <div className="card-header">
                                            <div className="card-icon phone">📱</div>
                                            <div>
                                                <div className="card-title">Phone Call (Demo)</div>
                                            </div>
                                        </div>
                                        <div className="card-content">
                                            <div className="setting-row">
                                                <label>Phone Number</label>
                                                <input
                                                    type="tel"
                                                    value={phoneNumber}
                                                    onChange={(e) => setPhoneNumber(e.target.value)}
                                                    placeholder="Enter phone number"
                                                    disabled={phoneCallStatus === 'calling' || phoneCallStatus === 'active'}
                                                    className="phone-input"
                                                />
                                            </div>
                                            <div className="phone-actions">
                                                {phoneCallStatus === 'idle' && (
                                                    <button
                                                        className="call-btn phone-call"
                                                        onClick={initiatePhoneCall}
                                                        disabled={!frejunConfig.configured || !phoneNumber.trim()}
                                                    >
                                                        <span className="btn-icon">📞</span>
                                                        <span className="btn-text">Call Now</span>
                                                    </button>
                                                )}
                                                {phoneCallStatus === 'active' && (
                                                    <button className="call-btn secondary" onClick={resetPhoneCall}>New Call</button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                    {/* Activity Log */}
                                    <div className="card">
                                        <div className="card-header">
                                            <div className="card-icon logs">📋</div>
                                            <div><div className="card-title">Activity Log</div></div>
                                        </div>
                                        <div className="card-content">
                                            <div className="logs-list">
                                                {logs.length === 0 ? <div className="no-logs">No activity...</div> :
                                                    [...logs].reverse().map((log, i) => <div key={i} className="log-item">{log}</div>)}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </section>
                        </>
                    )}

                    {activeView === 'agents' && (
                        <AgentList
                            API_URL={API_URL}
                            onEditAgent={handleEditAgent}
                            onCreateAgent={handleCreateAgent}
                            addLog={addLog}
                            user={user}
                        />
                    )}

                    {activeView === 'agent-config' && (
                        <AgentConfig
                            API_URL={API_URL}
                            agentId={selectedAgentId}
                            onSave={handleSaveAgent}
                            onCancel={handleCancelAgent}
                            addLog={addLog}
                        />
                    )}

                    {activeView === 'call-history' && (
                        <>
                            <section className="section">
                                <div className="call-history-filters">
                                    <input type="date" value={dateFilter} onChange={e => setDateFilter(e.target.value)} className="filter-input date-filter" />
                                    <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="filter-select">
                                        <option value="all">All Status</option>
                                        <option value="completed">Completed</option>
                                        <option value="answered">Answered</option>
                                        <option value="failed">Failed</option>
                                    </select>
                                </div>
                            </section>
                            <section className="section">
                                <div className="call-history-table-container">
                                    {loadingHistory ? <div className="loading-state">Loading...</div> :
                                        <table className="call-history-table">
                                            <thead>
                                                <tr>
                                                    <th>Date</th><th>Contact</th><th>Number</th><th>Duration</th><th>Status</th><th>Actions</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {getFilteredCallHistory().map(call => (
                                                    <tr key={call.id}>
                                                        <td>{formatDateTime(call.start_time || call.created_at)}</td>
                                                        <td>{call.from_number ? 'Outbound' : 'Unknown'}</td>
                                                        <td>{call.to_number || call.from_number || 'N/A'}</td>
                                                        <td>{formatDuration(call.duration_seconds || 0)}</td>
                                                        <td><span className={getStatusBadgeClass(call.status)}>{call.status}</span></td>
                                                        <td>
                                                            <button className="action-btn" onClick={() => call.has_transcript && viewTranscript(call.id)} disabled={!call.has_transcript}>👁️</button>
                                                            <button className="action-btn" onClick={() => call.recording_url && playRecording(call)} disabled={!call.recording_url}>
                                                                {playingRecordingId === call.id ? '⏹️' : '▶️'}
                                                            </button>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>}
                                </div>
                            </section>
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
