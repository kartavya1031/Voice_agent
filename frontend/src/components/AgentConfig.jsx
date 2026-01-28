import React, { useState, useEffect, useRef } from 'react';

const AgentConfig = ({ API_URL, agentId, onSave, onCancel, addLog, organizationId }) => {
    const [activeTab, setActiveTab] = useState('general');
    const [loading, setLoading] = useState(false);
    const [saveSuccess, setSaveSuccess] = useState(false);

    // Agent State
    const [agent, setAgent] = useState({
        name: '',
        description: '',
        phone_number: '',
        system_prompt: 'You are a helpful AI assistant for voice calls.\nBe concise and natural in your responses.\nAsk clarifying questions when needed.',
        recognition_language: 'en-IN',
        synthesis_voice_name: 'en-IN-NeerjaNeural',
        max_call_duration: 600,
        max_silence_duration: 20,
        active_kb_id: null,
        organization_id: organizationId || 'default-org-id'
    });

    // Resources State
    const [voices, setVoices] = useState([]);
    const [languages, setLanguages] = useState([]);
    const [knowledgeBases, setKnowledgeBases] = useState([]);

    // Upload State
    const [uploadingKB, setUploadingKB] = useState(false);
    const [newKBName, setNewKBName] = useState('');
    const [selectedFile, setSelectedFile] = useState(null);
    const [dragActive, setDragActive] = useState(false);
    const fileInputRef = useRef(null);

    // Prompt Variables State
    const [detectedVariables, setDetectedVariables] = useState([]);
    const [promptVariables, setPromptVariables] = useState({});
    const [loadingKB, setLoadingKB] = useState(false);

    // Initial Fetch
    useEffect(() => {
        fetchResources();
        fetchPromptVariables();
        if (agentId) {
            fetchAgent();
        } else {
            // Reset to defaults for Create Mode
            setAgent({
                name: '',
                description: '',
                phone_number: '',
                system_prompt: 'You are a helpful AI assistant for voice calls.\nBe concise and natural in your responses.\nAsk clarifying questions when needed.',
                recognition_language: 'en-IN',
                synthesis_voice_name: 'en-IN-NeerjaNeural',
                max_call_duration: 600,
                max_silence_duration: 20,
                active_kb_id: null,
                organization_id: organizationId || 'default-org-id'
            });
            setKnowledgeBases([]);
        }
    }, [agentId]);

    // Detect variables when system_prompt changes
    useEffect(() => {
        const detected = extractVariables(agent.system_prompt || '');
        setDetectedVariables(detected);
    }, [agent.system_prompt]);

    // Helper to extract {variable} patterns from prompt
    const extractVariables = (prompt) => {
        const pattern = /\{(\w+)\}/g;
        const matches = [...prompt.matchAll(pattern)];
        const unique = [...new Set(matches.map(m => m[1]))];
        return unique;
    };

    const fetchPromptVariables = async () => {
        try {
            const res = await fetch(`${API_URL}/api/agent/prompt-variables`);
            if (res.ok) {
                const data = await res.json();
                // Only set if we don't have agent-specific variables
                if (!agentId) {
                    setPromptVariables(data.variables || {});
                }
                setDetectedVariables(data.detected_variables || []);
            }
        } catch (err) {
            console.error('Error fetching prompt variables:', err);
        }
    };

    const handleVariableChange = (varName, value) => {
        const newVars = { ...promptVariables, [varName]: value };
        setPromptVariables(newVars);

        // Also update agent state so it saves with the agent
        setAgent(prev => ({
            ...prev,
            prompt_variables: JSON.stringify(newVars)
        }));
    };

    const fetchResources = async () => {
        try {
            const vRes = await fetch(`${API_URL}/api/agent/voices`);
            if (vRes.ok) {
                const vData = await vRes.json();
                setVoices(vData.voices || []);
                setLanguages(vData.languages || []);
            } else {
                console.error('Failed to fetch voices:', vRes.status);
                // Set default values if API fails
                setLanguages([
                    { code: 'en-IN', name: 'English (India)' },
                    { code: 'hi-IN', name: 'Hindi (India)' },
                    { code: 'en-US', name: 'English (US)' }
                ]);
            }
        } catch (err) {
            console.error('Error fetching resources:', err);
            // Set default values if API fails
            setLanguages([
                { code: 'en-IN', name: 'English (India)' },
                { code: 'hi-IN', name: 'Hindi (India)' },
                { code: 'en-US', name: 'English (US)' }
            ]);
        }
    };

    const fetchAgent = async () => {
        setLoading(true);
        try {
            const res = await fetch(`${API_URL}/api/agents/${agentId}`);
            const data = await res.json();
            setAgent(data);
            fetchKnowledgeBases(data.id);

            // Parse prompt_variables if it's a JSON string
            if (data.prompt_variables) {
                try {
                    const vars = typeof data.prompt_variables === 'string'
                        ? JSON.parse(data.prompt_variables)
                        : data.prompt_variables;
                    setPromptVariables(vars);
                } catch (e) {
                    console.error('Error parsing prompt_variables:', e);
                }
            }
        } catch (err) {
            addLog(`Error fetching agent: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    const fetchKnowledgeBases = async (id) => {
        setLoadingKB(true);
        try {
            const res = await fetch(`${API_URL}/api/agents/${id}/knowledge-bases`);
            if (res.ok) {
                const data = await res.json();
                setKnowledgeBases(data.knowledge_bases || []);
            } else {
                console.error('Failed to fetch knowledge bases:', res.status);
                setKnowledgeBases([]);
            }
        } catch (err) {
            console.error('Error fetching knowledge bases:', err);
            setKnowledgeBases([]);
        } finally {
            setLoadingKB(false);
        }
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setAgent(prev => ({ ...prev, [name]: value }));
    };

    const handleSave = async () => {
        setLoading(true);
        setSaveSuccess(false);
        try {
            let res;
            if (!agentId) {
                const orgRes = await fetch(`${API_URL}/api/organizations`);
                const orgData = await orgRes.json();
                let orgId = agent.organization_id;
                if (orgData.organizations && orgData.organizations.length > 0) {
                    orgId = orgData.organizations[0].id;
                } else {
                    const newOrg = await fetch(`${API_URL}/api/organizations`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name: 'Default Organization' })
                    });
                    const newOrgData = await newOrg.json();
                    if (newOrgData.organization) orgId = newOrgData.organization.id;
                }
                res = await fetch(`${API_URL}/api/agents`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ...agent, organization_id: orgId })
                });
            } else {
                res = await fetch(`${API_URL}/api/agents/${agentId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(agent)
                });
            }

            const data = await res.json();
            if (data.success || data.message) {
                setSaveSuccess(true);
                addLog(`✅ Agent saved successfully`);
                setTimeout(() => setSaveSuccess(false), 3000);
                onSave();
            } else {
                addLog(`❌ Failed to save agent: ${data.detail || 'Unknown error'}`);
            }
        } catch (err) {
            addLog(`Error saving agent: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    // Drag and drop handlers
    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === "dragenter" || e.type === "dragover") {
            setDragActive(true);
        } else if (e.type === "dragleave") {
            setDragActive(false);
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setSelectedFile(e.dataTransfer.files[0]);
        }
    };

    const uploadKB = async () => {
        if (!agentId) {
            alert("Please save the agent first before uploading files.");
            return;
        }
        if (!selectedFile || !newKBName.trim()) return;

        setUploadingKB(true);
        try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('name', newKBName.trim());

            const res = await fetch(`${API_URL}/api/agents/${agentId}/knowledge-base`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if (data.success) {
                addLog(`✅ Knowledge base uploaded`);
                fetchKnowledgeBases(agentId);
                setNewKBName('');
                setSelectedFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';
                if (data.knowledge_base.is_active) {
                    setAgent(prev => ({ ...prev, active_kb_id: data.knowledge_base.id }));
                }
            } else {
                addLog(`❌ Upload failed: ${data.detail || data.error}`);
            }
        } catch (err) {
            addLog(`Error uploading KB: ${err.message}`);
        } finally {
            setUploadingKB(false);
        }
    };

    const deleteKB = async (kbId) => {
        if (!confirm('Are you sure you want to delete this knowledge base?')) return;
        try {
            await fetch(`${API_URL}/api/agents/${agentId}/knowledge-bases/${kbId}`, { method: 'DELETE' });
            fetchKnowledgeBases(agentId);
            if (agent.active_kb_id == kbId) {
                setAgent(prev => ({ ...prev, active_kb_id: null }));
            }
            addLog('✅ Knowledge base deleted');
        } catch (e) {
            console.error(e);
        }
    };

    const activateKB = (kbId) => {
        setAgent(prev => ({ ...prev, active_kb_id: kbId }));
    };

    const tabs = [
        { id: 'general', label: 'General', icon: '⚙️' },
        { id: 'behavior', label: 'Behavior', icon: '🧠' },
        { id: 'voice', label: 'Voice Settings', icon: '🎙️' },
        { id: 'knowledge', label: 'Knowledge Base', icon: '📚', disabled: !agentId }
    ];

    if (loading && !agent.name) {
        return (
            <div className="agent-config-loading">
                <div className="loading-spinner"></div>
                <p>Loading agent configuration...</p>
            </div>
        );
    }

    return (
        <div className="agent-config-container">
            {/* Header */}
            <div className="config-header-bar">
                <div className="header-left">
                    <button className="back-btn" onClick={onCancel}>
                        <span>←</span> Back
                    </button>
                    <div className="header-title">
                        <h1>{agentId ? 'Edit Agent' : 'Create New Agent'}</h1>
                        <p className="subtitle">Configure your AI voice agent settings</p>
                    </div>
                </div>
                <div className="header-right">
                    {saveSuccess && (
                        <span className="save-success-badge">✓ Saved</span>
                    )}
                    <button className="cancel-btn" onClick={onCancel}>Cancel</button>
                    <button className="save-btn" onClick={handleSave} disabled={loading}>
                        {loading ? (
                            <>
                                <span className="btn-spinner"></span>
                                Saving...
                            </>
                        ) : (
                            <>
                                <span>💾</span> Save Changes
                            </>
                        )}
                    </button>
                </div>
            </div>

            <div className="config-layout">
                {/* Sidebar Tabs */}
                <div className="config-sidebar">
                    <nav className="tab-nav">
                        {tabs.map(tab => (
                            <button
                                key={tab.id}
                                className={`tab-nav-item ${activeTab === tab.id ? 'active' : ''} ${tab.disabled ? 'disabled' : ''}`}
                                onClick={() => !tab.disabled && setActiveTab(tab.id)}
                                disabled={tab.disabled}
                            >
                                <span className="tab-icon">{tab.icon}</span>
                                <span className="tab-label">{tab.label}</span>
                                {tab.disabled && <span className="tab-badge">Save first</span>}
                            </button>
                        ))}
                    </nav>

                    {agentId && (
                        <div className="sidebar-info">
                            <div className="info-card">
                                <span className="info-icon">ℹ️</span>
                                <p>Agent ID: <code>{agentId.substring(0, 8)}...</code></p>
                            </div>
                        </div>
                    )}
                </div>

                {/* Main Content */}
                <div className="config-main">
                    {/* General Tab */}
                    {activeTab === 'general' && (
                        <div className="tab-panel">
                            <div className="panel-header">
                                <h2>General Settings</h2>
                                <p>Basic information about your agent</p>
                            </div>

                            <div className="form-card">
                                <div className="form-section">
                                    <h3>Agent Identity</h3>
                                    <div className="form-grid">
                                        <div className="form-group full-width">
                                            <label>
                                                Agent Name <span className="required">*</span>
                                            </label>
                                            <input
                                                name="name"
                                                value={agent.name}
                                                onChange={handleChange}
                                                placeholder="e.g., Customer Support Agent"
                                                className="input-lg"
                                            />
                                            <span className="helper-text">Give your agent a descriptive name</span>
                                        </div>
                                        <div className="form-group full-width">
                                            <label>Description</label>
                                            <textarea
                                                name="description"
                                                value={agent.description || ''}
                                                onChange={handleChange}
                                                rows={3}
                                                placeholder="Describe what this agent does..."
                                            />
                                        </div>
                                    </div>
                                </div>

                                <div className="form-section">
                                    <h3>Phone Integration</h3>
                                    <div className="form-group">
                                        <label>
                                            <span className="label-icon">📞</span>
                                            Phone Number (FreJun)
                                        </label>
                                        <input
                                            name="phone_number"
                                            value={agent.phone_number || ''}
                                            onChange={handleChange}
                                            placeholder="+91XXXXXXXXXX"
                                        />
                                        <span className="helper-text">Incoming calls to this number will be routed to this agent</span>
                                    </div>
                                </div>

                                <div className="form-section">
                                    <h3>Call Limits</h3>
                                    <div className="form-grid two-col">
                                        <div className="form-group">
                                            <label>
                                                <span className="label-icon">⏱️</span>
                                                Max Call Duration
                                            </label>
                                            <div className="input-with-suffix">
                                                <input
                                                    type="number"
                                                    name="max_call_duration"
                                                    value={agent.max_call_duration}
                                                    onChange={handleChange}
                                                    min="60"
                                                    max="3600"
                                                />
                                                <span className="suffix">seconds</span>
                                            </div>
                                            <span className="helper-text">{Math.floor(agent.max_call_duration / 60)} minutes</span>
                                        </div>
                                        <div className="form-group">
                                            <label>
                                                <span className="label-icon">🔇</span>
                                                Silence Timeout
                                            </label>
                                            <div className="input-with-suffix">
                                                <input
                                                    type="number"
                                                    name="max_silence_duration"
                                                    value={agent.max_silence_duration}
                                                    onChange={handleChange}
                                                    min="5"
                                                    max="120"
                                                />
                                                <span className="suffix">seconds</span>
                                            </div>
                                            <span className="helper-text">End call after this much silence</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Behavior Tab */}
                    {activeTab === 'behavior' && (
                        <div className="tab-panel">
                            <div className="panel-header">
                                <h2>Agent Behavior</h2>
                                <p>Define how your agent responds and interacts</p>
                            </div>

                            <div className="form-card">
                                <div className="form-section">
                                    <div className="section-header">
                                        <h3>System Prompt</h3>
                                        <span className="section-badge">AI Instructions</span>
                                    </div>
                                    <div className="form-group">
                                        <div className="prompt-editor">
                                            <div className="prompt-toolbar">
                                                <span className="toolbar-hint">Use {'{variable}'} for dynamic content</span>
                                                <span className="char-count">{agent.system_prompt?.length || 0} characters</span>
                                            </div>
                                            <textarea
                                                name="system_prompt"
                                                value={agent.system_prompt}
                                                onChange={handleChange}
                                                rows={18}
                                                className="prompt-textarea"
                                                placeholder="Enter the system prompt that defines your agent's behavior..."
                                            />
                                        </div>
                                    </div>
                                </div>

                                <div className="tip-card">
                                    <span className="tip-icon">💡</span>
                                    <div className="tip-content">
                                        <strong>Pro Tip:</strong> Be specific about the agent's role, tone, and response format.
                                        Include example responses for consistent behavior.
                                    </div>
                                </div>
                            </div>

                            {/* Dynamic Variables Section */}
                            {detectedVariables.length > 0 && (
                                <div className="form-card">
                                    <div className="form-section">
                                        <div className="section-header">
                                            <h3>Dynamic Variables</h3>
                                            <span className="section-badge">{detectedVariables.length} detected</span>
                                        </div>
                                        <p className="section-description">
                                            These variables were detected in your prompt. Set their values below:
                                        </p>

                                        <div className="variables-grid">
                                            {detectedVariables.map(varName => (
                                                <div key={varName} className="variable-item">
                                                    <label className="variable-label">
                                                        <span className="var-badge">{`{${varName}}`}</span>
                                                    </label>
                                                    <input
                                                        type="text"
                                                        placeholder={`Enter value for ${varName}`}
                                                        value={promptVariables[varName] || ''}
                                                        onChange={(e) => handleVariableChange(varName, e.target.value)}
                                                        className="variable-input"
                                                    />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {detectedVariables.length === 0 && (
                                <div className="form-card">
                                    <div className="empty-variables">
                                        <span className="empty-icon">🏷️</span>
                                        <h4>No Dynamic Variables</h4>
                                        <p>Add <code>{'{variable_name}'}</code> placeholders to your prompt to create dynamic content.</p>
                                        <p className="example">Example: "Hello {'{customer_name}'}, I'm {'{agent_name}'} from {'{company}'}"</p>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Voice Tab */}
                    {activeTab === 'voice' && (
                        <div className="tab-panel">
                            <div className="panel-header">
                                <h2>Voice Settings</h2>
                                <p>Configure speech recognition and synthesis</p>
                            </div>

                            <div className="form-card">
                                <div className="form-section">
                                    <h3>Speech Recognition</h3>
                                    <div className="form-group">
                                        <label>
                                            <span className="label-icon">🌍</span>
                                            Recognition Language
                                        </label>
                                        {languages.length === 0 ? (
                                            <div className="loading-field">Loading languages...</div>
                                        ) : (
                                            <select
                                                name="recognition_language"
                                                value={agent.recognition_language}
                                                onChange={handleChange}
                                                className="select-lg"
                                            >
                                                {languages.map(l => (
                                                    <option key={l.code} value={l.code}>{l.name}</option>
                                                ))}
                                            </select>
                                        )}
                                        <span className="helper-text">Language your customers will speak in</span>
                                    </div>
                                </div>

                                <div className="form-section">
                                    <h3>Voice Synthesis</h3>
                                    <div className="form-group">
                                        <label>
                                            <span className="label-icon">🗣️</span>
                                            Agent Voice
                                        </label>
                                        <div className="voice-selector">
                                            {voices.length === 0 ? (
                                                <div className="loading-field">Loading voices...</div>
                                            ) : (
                                                <select
                                                    name="synthesis_voice_name"
                                                    value={agent.synthesis_voice_name}
                                                    onChange={handleChange}
                                                    className="select-lg"
                                                >
                                                    {(() => {
                                                        const langPrefix = (agent.recognition_language || 'en').split('-')[0];
                                                        const filteredVoices = voices.filter(v => v.locale && v.locale.startsWith(langPrefix));
                                                        if (filteredVoices.length === 0) {
                                                            return <option value="">No voices available for this language</option>;
                                                        }
                                                        return filteredVoices.map(v => (
                                                            <option key={v.shortName} value={v.shortName}>
                                                                {v.localName} ({v.gender})
                                                            </option>
                                                        ));
                                                    })()}
                                                </select>
                                            )}
                                        </div>
                                        <span className="helper-text">Neural voice for text-to-speech</span>
                                    </div>
                                </div>

                                <div className="voice-preview-card">
                                    <div className="preview-icon">🎧</div>
                                    <div className="preview-content">
                                        <strong>Voice Preview</strong>
                                        <p>Selected: {agent.synthesis_voice_name || 'None selected'}</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Knowledge Tab */}
                    {activeTab === 'knowledge' && (
                        <div className="tab-panel">
                            <div className="panel-header">
                                <h2>Knowledge Base</h2>
                                <p>Upload documents for RAG-powered responses</p>
                            </div>

                            {/* Upload Section */}
                            <div className="form-card">
                                <div className="form-section">
                                    <h3>Upload New Knowledge</h3>

                                    <div className="form-group">
                                        <label>Knowledge Base Name</label>
                                        <input
                                            type="text"
                                            placeholder="e.g., Product Manual, FAQ Document"
                                            value={newKBName}
                                            onChange={(e) => setNewKBName(e.target.value)}
                                        />
                                    </div>

                                    <div
                                        className={`dropzone ${dragActive ? 'drag-active' : ''} ${selectedFile ? 'has-file' : ''}`}
                                        onDragEnter={handleDrag}
                                        onDragLeave={handleDrag}
                                        onDragOver={handleDrag}
                                        onDrop={handleDrop}
                                        onClick={() => fileInputRef.current?.click()}
                                    >
                                        <input
                                            type="file"
                                            ref={fileInputRef}
                                            onChange={(e) => setSelectedFile(e.target.files[0])}
                                            accept=".pdf,.txt,.md"
                                            hidden
                                        />
                                        {selectedFile ? (
                                            <div className="file-selected">
                                                <span className="file-icon">📄</span>
                                                <div className="file-info">
                                                    <strong>{selectedFile.name}</strong>
                                                    <span>{(selectedFile.size / 1024).toFixed(1)} KB</span>
                                                </div>
                                                <button
                                                    className="remove-file"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        setSelectedFile(null);
                                                    }}
                                                >
                                                    ✕
                                                </button>
                                            </div>
                                        ) : (
                                            <div className="dropzone-content">
                                                <span className="dropzone-icon">📁</span>
                                                <p><strong>Click to upload</strong> or drag and drop</p>
                                                <span className="dropzone-hint">PDF, TXT, or MD files (max 10MB)</span>
                                            </div>
                                        )}
                                    </div>

                                    <button
                                        className="upload-btn"
                                        onClick={uploadKB}
                                        disabled={uploadingKB || !selectedFile || !newKBName.trim()}
                                    >
                                        {uploadingKB ? (
                                            <>
                                                <span className="btn-spinner"></span>
                                                Uploading...
                                            </>
                                        ) : (
                                            <>
                                                <span>⬆️</span>
                                                Upload Knowledge Base
                                            </>
                                        )}
                                    </button>
                                </div>
                            </div>

                            {/* Knowledge Base List */}
                            <div className="form-card">
                                <div className="form-section">
                                    <div className="section-header">
                                        <h3>Attached Knowledge Bases</h3>
                                        <span className="count-badge">{knowledgeBases.length} files</span>
                                    </div>

                                    {loadingKB ? (
                                        <div className="loading-state">
                                            <span className="loading-spinner"></span>
                                            <p>Loading knowledge bases...</p>
                                        </div>
                                    ) : knowledgeBases.length === 0 ? (
                                        <div className="empty-state">
                                            <span className="empty-icon">📭</span>
                                            <h4>No knowledge bases yet</h4>
                                            <p>Upload documents to give your agent contextual knowledge</p>
                                        </div>
                                    ) : (
                                        <div className="kb-list">
                                            {knowledgeBases.map(kb => (
                                                <div key={kb.id} className={`kb-item ${agent.active_kb_id === kb.id ? 'active' : ''}`}>
                                                    <div className="kb-icon">📚</div>
                                                    <div className="kb-info">
                                                        <strong>{kb.name}</strong>
                                                        <span className="kb-meta">
                                                            {kb.chunk_count} chunks • {kb.filename || 'Uploaded file'}
                                                        </span>
                                                    </div>
                                                    <div className="kb-actions">
                                                        {agent.active_kb_id === kb.id ? (
                                                            <span className="active-badge">
                                                                <span>✓</span> Active
                                                            </span>
                                                        ) : (
                                                            <button
                                                                className="activate-btn"
                                                                onClick={() => activateKB(kb.id)}
                                                            >
                                                                Activate
                                                            </button>
                                                        )}
                                                        <button
                                                            className="delete-btn"
                                                            onClick={() => deleteKB(kb.id)}
                                                            title="Delete knowledge base"
                                                        >
                                                            🗑️
                                                        </button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            <style>{`
                .agent-config-container {
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    background: var(--bg-light, #f8f9fa);
                }

                .agent-config-loading {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    height: 100%;
                    gap: 16px;
                    color: var(--text-muted);
                }

                .loading-spinner, .btn-spinner {
                    width: 24px;
                    height: 24px;
                    border: 3px solid #e5e7eb;
                    border-top-color: var(--accent, #c4704f);
                    border-radius: 50%;
                    animation: spin 0.8s linear infinite;
                }

                .btn-spinner {
                    width: 16px;
                    height: 16px;
                    border-width: 2px;
                }

                .loading-field {
                    padding: 12px 16px;
                    background: var(--bg-light, #f8f9fa);
                    border: 1px solid var(--border, #e5e7eb);
                    border-radius: 8px;
                    color: var(--text-muted, #6b7280);
                    font-size: 14px;
                }

                @keyframes spin {
                    to { transform: rotate(360deg); }
                }

                /* Header */
                .config-header-bar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 16px 32px;
                    background: white;
                    border-bottom: 1px solid var(--border, #e5e7eb);
                    flex-shrink: 0;
                }

                .header-left {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                }

                .back-btn {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px 16px;
                    background: transparent;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    color: var(--text-dark);
                    cursor: pointer;
                    font-size: 14px;
                    transition: all 0.2s;
                }

                .back-btn:hover {
                    background: var(--bg-light);
                }

                .header-title h1 {
                    font-size: 1.5rem;
                    font-weight: 600;
                    color: var(--text-dark);
                    margin: 0;
                }

                .subtitle {
                    font-size: 0.875rem;
                    color: var(--text-muted);
                    margin: 4px 0 0;
                }

                .header-right {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }

                .save-success-badge {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                    padding: 8px 16px;
                    background: #dcfce7;
                    color: #16a34a;
                    border-radius: 20px;
                    font-size: 14px;
                    font-weight: 500;
                    animation: fadeIn 0.3s ease;
                }

                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(-10px); }
                    to { opacity: 1; transform: translateY(0); }
                }

                .cancel-btn {
                    padding: 10px 20px;
                    background: white;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    color: var(--text-dark);
                    font-size: 14px;
                    cursor: pointer;
                    transition: all 0.2s;
                }

                .cancel-btn:hover {
                    background: var(--bg-light);
                }

                .save-btn {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 10px 24px;
                    background: var(--accent, #c4704f);
                    border: none;
                    border-radius: 8px;
                    color: white;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s;
                }

                .save-btn:hover:not(:disabled) {
                    background: #b5623f;
                }

                .save-btn:disabled {
                    opacity: 0.6;
                    cursor: not-allowed;
                }

                /* Layout */
                .config-layout {
                    display: flex;
                    flex: 1;
                    overflow: hidden;
                }

                /* Sidebar */
                .config-sidebar {
                    width: 240px;
                    background: white;
                    border-right: 1px solid var(--border);
                    padding: 24px 16px;
                    display: flex;
                    flex-direction: column;
                    flex-shrink: 0;
                }

                .tab-nav {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                }

                .tab-nav-item {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 12px 16px;
                    background: transparent;
                    border: none;
                    border-radius: 8px;
                    color: var(--text-muted);
                    font-size: 14px;
                    cursor: pointer;
                    transition: all 0.2s;
                    text-align: left;
                }

                .tab-nav-item:hover:not(.disabled) {
                    background: var(--bg-light);
                    color: var(--text-dark);
                }

                .tab-nav-item.active {
                    background: #fef3ee;
                    color: var(--accent);
                    font-weight: 500;
                }

                .tab-nav-item.disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }

                .tab-icon {
                    font-size: 18px;
                }

                .tab-badge {
                    margin-left: auto;
                    font-size: 10px;
                    padding: 2px 6px;
                    background: #f3f4f6;
                    border-radius: 4px;
                    color: var(--text-muted);
                }

                .sidebar-info {
                    margin-top: auto;
                    padding-top: 20px;
                    border-top: 1px solid var(--border);
                }

                .info-card {
                    display: flex;
                    align-items: flex-start;
                    gap: 8px;
                    padding: 12px;
                    background: var(--bg-light);
                    border-radius: 8px;
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .info-card code {
                    background: white;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-family: monospace;
                }

                /* Main Content */
                .config-main {
                    flex: 1;
                    overflow-y: auto;
                    padding: 24px 32px;
                }

                .tab-panel {
                    max-width: 800px;
                }

                .panel-header {
                    margin-bottom: 24px;
                }

                .panel-header h2 {
                    font-size: 1.25rem;
                    font-weight: 600;
                    color: var(--text-dark);
                    margin: 0;
                }

                .panel-header p {
                    color: var(--text-muted);
                    margin: 4px 0 0;
                    font-size: 14px;
                }

                /* Form Cards */
                .form-card {
                    background: white;
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 24px;
                    margin-bottom: 20px;
                }

                .form-section {
                    margin-bottom: 24px;
                }

                .form-section:last-child {
                    margin-bottom: 0;
                }

                .form-section h3 {
                    font-size: 14px;
                    font-weight: 600;
                    color: var(--text-dark);
                    margin: 0 0 16px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid var(--border);
                }

                .section-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 16px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid var(--border);
                }

                .section-header h3 {
                    margin: 0;
                    padding: 0;
                    border: none;
                }

                .section-badge, .count-badge {
                    font-size: 11px;
                    padding: 4px 10px;
                    background: #fef3ee;
                    color: var(--accent);
                    border-radius: 12px;
                    font-weight: 500;
                }

                .form-grid {
                    display: grid;
                    gap: 20px;
                }

                .form-grid.two-col {
                    grid-template-columns: 1fr 1fr;
                }

                .form-group {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }

                .form-group.full-width {
                    grid-column: 1 / -1;
                }

                .form-group label {
                    font-size: 13px;
                    font-weight: 500;
                    color: var(--text-dark);
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .label-icon {
                    font-size: 16px;
                }

                .required {
                    color: #ef4444;
                }

                .helper-text {
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .agent-config-container input,
                .agent-config-container select,
                .agent-config-container textarea {
                    padding: 10px 14px;
                    background: white;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    font-size: 14px;
                    color: var(--text-dark);
                    transition: all 0.2s;
                }

                .agent-config-container input:focus,
                .agent-config-container select:focus,
                .agent-config-container textarea:focus {
                    outline: none;
                    border-color: var(--accent);
                    box-shadow: 0 0 0 3px rgba(196, 112, 79, 0.1);
                }

                .input-lg, .select-lg {
                    padding: 12px 16px;
                    font-size: 15px;
                }

                .agent-config-container textarea {
                    resize: vertical;
                    min-height: 80px;
                }

                .input-with-suffix {
                    display: flex;
                    align-items: stretch;
                }

                .input-with-suffix input {
                    border-radius: 8px 0 0 8px;
                    flex: 1;
                }

                .input-with-suffix .suffix {
                    display: flex;
                    align-items: center;
                    padding: 0 14px;
                    background: var(--bg-light);
                    border: 1px solid var(--border);
                    border-left: none;
                    border-radius: 0 8px 8px 0;
                    font-size: 13px;
                    color: var(--text-muted);
                }

                /* Prompt Editor */
                .prompt-editor {
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    overflow: hidden;
                }

                .prompt-toolbar {
                    display: flex;
                    justify-content: space-between;
                    padding: 10px 14px;
                    background: var(--bg-light);
                    border-bottom: 1px solid var(--border);
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .prompt-textarea {
                    border: none !important;
                    border-radius: 0 !important;
                    font-family: 'Monaco', 'Menlo', monospace;
                    font-size: 13px;
                    line-height: 1.6;
                    resize: none;
                }

                .prompt-textarea:focus {
                    box-shadow: none !important;
                }

                /* Tip Card */
                .tip-card {
                    display: flex;
                    gap: 12px;
                    padding: 16px;
                    background: #fef3c7;
                    border-radius: 8px;
                    margin-top: 16px;
                }

                .tip-icon {
                    font-size: 20px;
                }

                .tip-content {
                    font-size: 13px;
                    color: #92400e;
                    line-height: 1.5;
                }

                /* Voice Preview */
                .voice-preview-card {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    padding: 20px;
                    background: linear-gradient(135deg, #fef3ee, #fff);
                    border: 1px solid #fde8dc;
                    border-radius: 12px;
                    margin-top: 16px;
                }

                .preview-icon {
                    font-size: 32px;
                }

                .preview-content strong {
                    display: block;
                    font-size: 14px;
                    color: var(--text-dark);
                    margin-bottom: 4px;
                }

                .preview-content p {
                    font-size: 13px;
                    color: var(--text-muted);
                    margin: 0;
                }

                /* Dropzone */
                .dropzone {
                    border: 2px dashed var(--border);
                    border-radius: 12px;
                    padding: 32px;
                    text-align: center;
                    cursor: pointer;
                    transition: all 0.2s;
                    background: var(--bg-light);
                }

                .dropzone:hover, .dropzone.drag-active {
                    border-color: var(--accent);
                    background: #fef3ee;
                }

                .dropzone.has-file {
                    border-style: solid;
                    border-color: var(--accent);
                    background: white;
                }

                .dropzone-content {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 8px;
                }

                .dropzone-icon {
                    font-size: 40px;
                    opacity: 0.6;
                }

                .dropzone-content p {
                    margin: 0;
                    color: var(--text-dark);
                }

                .dropzone-hint {
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .file-selected {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }

                .file-icon {
                    font-size: 32px;
                }

                .file-info {
                    display: flex;
                    flex-direction: column;
                    text-align: left;
                }

                .file-info strong {
                    color: var(--text-dark);
                }

                .file-info span {
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .remove-file {
                    margin-left: auto;
                    width: 28px;
                    height: 28px;
                    border-radius: 50%;
                    background: #fee2e2;
                    border: none;
                    color: #ef4444;
                    cursor: pointer;
                    font-size: 14px;
                }

                .upload-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    width: 100%;
                    padding: 14px;
                    background: var(--accent);
                    border: none;
                    border-radius: 8px;
                    color: white;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    margin-top: 16px;
                    transition: all 0.2s;
                }

                .upload-btn:hover:not(:disabled) {
                    background: #b5623f;
                }

                .upload-btn:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }

                /* Loading State */
                .loading-state {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    padding: 40px 20px;
                    gap: 12px;
                    color: var(--text-muted);
                }

                /* Empty State */
                .empty-state {
                    text-align: center;
                    padding: 40px 20px;
                    color: var(--text-muted);
                }

                .empty-icon {
                    font-size: 48px;
                    display: block;
                    margin-bottom: 16px;
                    opacity: 0.5;
                }

                .empty-state h4 {
                    margin: 0 0 8px;
                    color: var(--text-dark);
                }

                .empty-state p {
                    margin: 0;
                    font-size: 14px;
                }

                /* KB List */
                .kb-list {
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }

                .kb-item {
                    display: flex;
                    align-items: center;
                    gap: 16px;
                    padding: 16px;
                    background: var(--bg-light);
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    transition: all 0.2s;
                }

                .kb-item.active {
                    background: #f0fdf4;
                    border-color: #86efac;
                }

                .kb-icon {
                    font-size: 28px;
                }

                .kb-info {
                    flex: 1;
                }

                .kb-info strong {
                    display: block;
                    color: var(--text-dark);
                    margin-bottom: 4px;
                }

                .kb-meta {
                    font-size: 12px;
                    color: var(--text-muted);
                }

                .kb-actions {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .active-badge {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                    padding: 6px 12px;
                    background: #22c55e;
                    color: white;
                    border-radius: 20px;
                    font-size: 12px;
                    font-weight: 500;
                }

                .activate-btn {
                    padding: 6px 16px;
                    background: white;
                    border: 1px solid var(--border);
                    border-radius: 6px;
                    font-size: 13px;
                    cursor: pointer;
                    transition: all 0.2s;
                }

                .activate-btn:hover {
                    border-color: var(--accent);
                    color: var(--accent);
                }

                .delete-btn {
                    padding: 6px 10px;
                    background: transparent;
                    border: none;
                    font-size: 16px;
                    cursor: pointer;
                    opacity: 0.5;
                    transition: all 0.2s;
                }

                .delete-btn:hover {
                    opacity: 1;
                }

                /* Dynamic Variables */
                .section-description {
                    color: var(--text-muted);
                    font-size: 14px;
                    margin-bottom: 16px;
                }

                .variables-grid {
                    display: grid;
                    gap: 16px;
                }

                .variable-item {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }

                .variable-label {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .var-badge {
                    display: inline-block;
                    padding: 4px 10px;
                    background: linear-gradient(135deg, #fef3ee, #fde8dc);
                    border: 1px solid #f8d4c3;
                    border-radius: 6px;
                    font-family: monospace;
                    font-size: 13px;
                    color: var(--accent);
                    font-weight: 500;
                }

                .variable-input {
                    padding: 12px 16px;
                    background: white;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    font-size: 14px;
                    transition: all 0.2s;
                }

                .variable-input:focus {
                    outline: none;
                    border-color: var(--accent);
                    box-shadow: 0 0 0 3px rgba(196, 112, 79, 0.1);
                }

                .empty-variables {
                    text-align: center;
                    padding: 32px 20px;
                    color: var(--text-muted);
                }

                .empty-variables .empty-icon {
                    font-size: 40px;
                    margin-bottom: 12px;
                    opacity: 0.5;
                }

                .empty-variables h4 {
                    margin: 0 0 8px;
                    color: var(--text-dark);
                }

                .empty-variables p {
                    margin: 0;
                    font-size: 14px;
                }

                .empty-variables code {
                    background: #f3f4f6;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-size: 13px;
                }

                .empty-variables .example {
                    margin-top: 12px;
                    font-style: italic;
                    color: var(--text-muted);
                    font-size: 13px;
                }

                /* Responsive */
                @media (max-width: 768px) {
                    .config-layout {
                        flex-direction: column;
                    }

                    .config-sidebar {
                        width: 100%;
                        flex-direction: row;
                        padding: 12px;
                        overflow-x: auto;
                    }

                    .tab-nav {
                        flex-direction: row;
                    }

                    .sidebar-info {
                        display: none;
                    }

                    .config-main {
                        padding: 20px;
                    }

                    .form-grid.two-col {
                        grid-template-columns: 1fr;
                    }

                    .config-header-bar {
                        flex-direction: column;
                        gap: 16px;
                        padding: 16px;
                    }

                    .header-left, .header-right {
                        width: 100%;
                        justify-content: space-between;
                    }
                }
            `}</style>
        </div>
    );
};

export default AgentConfig;
