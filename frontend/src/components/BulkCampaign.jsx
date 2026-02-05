import React, { useState, useEffect, useRef } from 'react';

/**
 * BulkCampaign Component
 * 
 * Allows users to upload a CSV file with phone numbers and dynamic variables,
 * then start a bulk calling campaign using a selected agent.
 */
const BulkCampaign = ({ API_URL, agents, user, addLog }) => {
    const [selectedAgentId, setSelectedAgentId] = useState('');
    const [selectedAgent, setSelectedAgent] = useState(null);
    const [promptVariables, setPromptVariables] = useState([]);
    const [csvData, setCsvData] = useState([]);
    const [csvHeaders, setCsvHeaders] = useState([]);
    const [campaignName, setCampaignName] = useState('');
    const [callDelay, setCallDelay] = useState(30);
    const [isUploading, setIsUploading] = useState(false);
    const [campaign, setCampaign] = useState(null);
    const [isPolling, setIsPolling] = useState(false);
    const [dragActive, setDragActive] = useState(false);
    const fileInputRef = useRef(null);

    // User-specific localStorage key for active campaign
    const campaignStorageKey = user?.id ? `activeCampaignId_${user.id}` : 'activeCampaignId';

    // Load active campaign from localStorage on mount
    useEffect(() => {
        if (!user?.id) return; // Wait for user to be loaded

        const savedCampaignId = localStorage.getItem(campaignStorageKey);
        if (savedCampaignId) {
            // Fetch campaign status
            fetch(`${API_URL}/api/campaigns/${savedCampaignId}/status`)
                .then(res => res.json())
                .then(data => {
                    if (data && data.status && data.status !== 'completed' && data.status !== 'stopped' && data.status !== 'failed') {
                        setCampaign(data);
                        setIsPolling(true);
                        addLog(`📊 Resumed tracking campaign: ${data.name}`);
                    } else if (data && data.status) {
                        // Campaign finished, show final status then clear
                        setCampaign(data);
                        localStorage.removeItem(campaignStorageKey);
                    } else {
                        localStorage.removeItem(campaignStorageKey);
                    }
                })
                .catch(() => {
                    localStorage.removeItem(campaignStorageKey);
                });
        }
    }, [API_URL, user?.id, campaignStorageKey]);

    // Extract {variables} from agent's system prompt
    const extractVariables = (prompt) => {
        if (!prompt) return [];
        const regex = /\{([^}]+)\}/g;
        const matches = [...prompt.matchAll(regex)];
        return [...new Set(matches.map(m => m[1]))];
    };

    // When agent is selected, fetch its details and extract variables
    useEffect(() => {
        if (selectedAgentId) {
            const agent = agents.find(a => a.id === selectedAgentId);
            if (agent) {
                setSelectedAgent(agent);
                const vars = extractVariables(agent.system_prompt);
                setPromptVariables(vars);
                console.log('Agent selected:', agent.name, 'Variables:', vars);
            }
        } else {
            setSelectedAgent(null);
            setPromptVariables([]);
        }
    }, [selectedAgentId, agents]);

    // Parse CSV file
    const parseCSV = (text) => {
        const lines = text.split('\n').filter(line => line.trim());
        if (lines.length === 0) return { headers: [], data: [] };

        // Parse headers
        const headers = lines[0].split(',').map(h => h.trim().toLowerCase());

        // Parse data rows
        const data = [];
        for (let i = 1; i < lines.length; i++) {
            const values = lines[i].split(',').map(v => v.trim());
            if (values.length >= headers.length) {
                const row = {};
                headers.forEach((h, idx) => {
                    row[h] = values[idx] || '';
                });
                data.push(row);
            }
        }

        return { headers, data };
    };

    // Handle file upload
    const handleFileChange = (e) => {
        const file = e.target.files?.[0];
        if (file) {
            processFile(file);
        }
    };

    const processFile = (file) => {
        if (!file.name.endsWith('.csv')) {
            addLog('❌ Please upload a CSV file');
            return;
        }

        setIsUploading(true);
        const reader = new FileReader();
        reader.onload = (event) => {
            const text = event.target.result;
            const { headers, data } = parseCSV(text);

            setCsvHeaders(headers);
            setCsvData(data);

            // Auto-generate campaign name
            if (!campaignName) {
                setCampaignName(`Campaign ${new Date().toLocaleDateString()}`);
            }

            addLog(`✅ CSV loaded: ${data.length} contacts, columns: ${headers.join(', ')}`);
            setIsUploading(false);
        };
        reader.onerror = () => {
            addLog('❌ Error reading CSV file');
            setIsUploading(false);
        };
        reader.readAsText(file);
    };

    // Drag and drop handlers
    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            processFile(e.dataTransfer.files[0]);
        }
    };

    // Validate CSV has required columns
    const validateCSV = () => {
        if (!csvHeaders.includes('phone_number') && !csvHeaders.includes('phone')) {
            return 'CSV must have a "phone_number" or "phone" column';
        }

        // Check for missing variable columns
        const missingVars = promptVariables.filter(v =>
            !csvHeaders.includes(v.toLowerCase())
        );
        if (missingVars.length > 0) {
            return `CSV is missing columns for variables: ${missingVars.join(', ')}`;
        }

        return null;
    };

    // Start campaign
    const startCampaign = async () => {
        const validationError = validateCSV();
        if (validationError) {
            addLog(`❌ ${validationError}`);
            return;
        }

        // Prepare calls data
        const phoneColumn = csvHeaders.includes('phone_number') ? 'phone_number' : 'phone';
        const calls = csvData.map(row => {
            const variables = {};
            promptVariables.forEach(v => {
                const key = v.toLowerCase();
                if (row[key]) {
                    variables[v] = row[key];
                }
            });
            return {
                phone_number: row[phoneColumn],
                variables
            };
        });

        try {
            addLog(`🚀 Starting campaign with ${calls.length} calls...`);

            const response = await fetch(`${API_URL}/api/campaigns/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    agent_id: selectedAgentId,
                    user_id: user?.id || '',
                    name: campaignName,
                    call_delay_seconds: callDelay,
                    calls
                })
            });

            const data = await response.json();
            if (data.success) {
                addLog(`✅ Campaign started: ${data.campaign_id}`);
                setCampaign({ id: data.campaign_id, status: 'running' });
                setIsPolling(true);
                // Save to localStorage so we can resume tracking after page refresh (user-specific key)
                localStorage.setItem(campaignStorageKey, data.campaign_id);
            } else {
                addLog(`❌ Failed to start campaign: ${data.detail || 'Unknown error'}`);
            }
        } catch (err) {
            addLog(`❌ Error starting campaign: ${err.message}`);
        }
    };

    // Poll campaign status
    useEffect(() => {
        if (!isPolling || !campaign?.id) return;

        const pollInterval = setInterval(async () => {
            try {
                const response = await fetch(`${API_URL}/api/campaigns/${campaign.id}/status`);
                const data = await response.json();
                setCampaign(data);

                if (data.status === 'completed' || data.status === 'stopped' || data.status === 'failed') {
                    setIsPolling(false);
                    localStorage.removeItem(campaignStorageKey);
                    addLog(`🎉 Campaign ${data.status}: ${data.successful_calls}/${data.total_calls} successful`);
                }
            } catch (err) {
                console.error('Error polling campaign status:', err);
            }
        }, 3000);

        return () => clearInterval(pollInterval);
    }, [isPolling, campaign?.id]);

    // Stop campaign
    const stopCampaign = async () => {
        if (!campaign?.id) return;

        try {
            await fetch(`${API_URL}/api/campaigns/${campaign.id}/stop`, { method: 'POST' });
            addLog('⏹️ Campaign stop requested');
        } catch (err) {
            addLog(`❌ Error stopping campaign: ${err.message}`);
        }
    };

    // Reset
    const resetCampaign = () => {
        setCampaign(null);
        setCsvData([]);
        setCsvHeaders([]);
        setCampaignName('');
        setIsPolling(false);
    };

    return (
        <div className="bulk-campaign">
            <h3>📞 Bulk Calling Campaign</h3>

            {!campaign && (
                <>
                    {/* Agent Selection */}
                    <div className="form-group">
                        <label>Select Agent</label>
                        <select
                            value={selectedAgentId}
                            onChange={(e) => setSelectedAgentId(e.target.value)}
                            className="form-select"
                        >
                            <option value="">-- Select an agent --</option>
                            {agents.map(agent => (
                                <option key={agent.id} value={agent.id}>{agent.name}</option>
                            ))}
                        </select>
                    </div>

                    {/* Show required variables */}
                    {selectedAgent && (
                        <div className="variables-info">
                            <h4>📝 Required CSV Columns</h4>
                            <div className="variable-chips">
                                <span className="chip required">phone_number</span>
                                {promptVariables.map(v => (
                                    <span key={v} className="chip variable">{`{${v}}`}</span>
                                ))}
                            </div>
                            {promptVariables.length === 0 && (
                                <p className="hint">No dynamic variables found in agent's prompt</p>
                            )}
                        </div>
                    )}

                    {/* CSV Upload */}
                    {selectedAgent && (
                        <div
                            className={`csv-dropzone ${dragActive ? 'active' : ''}`}
                            onDragEnter={handleDrag}
                            onDragLeave={handleDrag}
                            onDragOver={handleDrag}
                            onDrop={handleDrop}
                            onClick={() => fileInputRef.current?.click()}
                        >
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept=".csv"
                                onChange={handleFileChange}
                                style={{ display: 'none' }}
                            />
                            {isUploading ? (
                                <div className="upload-progress">Processing CSV...</div>
                            ) : csvData.length > 0 ? (
                                <div className="upload-success">
                                    ✅ {csvData.length} contacts loaded
                                    <br />
                                    <small>Click to upload a different file</small>
                                </div>
                            ) : (
                                <div className="upload-prompt">
                                    📁 Drop CSV file here or click to browse
                                </div>
                            )}
                        </div>
                    )}

                    {/* CSV Preview */}
                    {csvData.length > 0 && (
                        <div className="csv-preview">
                            <h4>Preview ({csvData.length} contacts)</h4>
                            <div className="preview-table">
                                <table>
                                    <thead>
                                        <tr>
                                            {csvHeaders.map(h => <th key={h}>{h}</th>)}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {csvData.slice(0, 5).map((row, idx) => (
                                            <tr key={idx}>
                                                {csvHeaders.map(h => <td key={h}>{row[h]}</td>)}
                                            </tr>
                                        ))}
                                        {csvData.length > 5 && (
                                            <tr className="more-row">
                                                <td colSpan={csvHeaders.length}>
                                                    ... and {csvData.length - 5} more
                                                </td>
                                            </tr>
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* Campaign Settings */}
                    {csvData.length > 0 && (
                        <div className="campaign-settings">
                            <div className="form-group">
                                <label>Campaign Name</label>
                                <input
                                    type="text"
                                    value={campaignName}
                                    onChange={(e) => setCampaignName(e.target.value)}
                                    placeholder="Enter campaign name"
                                    className="form-input"
                                />
                            </div>
                            <div className="form-group">
                                <label>Delay Between Calls (seconds)</label>
                                <input
                                    type="number"
                                    value={callDelay}
                                    onChange={(e) => setCallDelay(parseInt(e.target.value) || 30)}
                                    min="5"
                                    max="300"
                                    className="form-input"
                                />
                            </div>
                            <button className="start-campaign-btn" onClick={startCampaign}>
                                🚀 Start Campaign ({csvData.length} calls)
                            </button>
                        </div>
                    )}
                </>
            )}

            {/* Campaign Progress */}
            {campaign && (
                <div className="campaign-progress">
                    <h4>📊 Campaign: {campaign.name}</h4>
                    <div className="progress-stats">
                        <div className="stat">
                            <span className="stat-value">{campaign.completed_calls || 0}</span>
                            <span className="stat-label">/ {campaign.total_calls} Completed</span>
                        </div>
                        <div className="stat success">
                            <span className="stat-value">{campaign.successful_calls || 0}</span>
                            <span className="stat-label">Successful</span>
                        </div>
                        <div className="stat error">
                            <span className="stat-value">{campaign.failed_calls || 0}</span>
                            <span className="stat-label">Failed</span>
                        </div>
                    </div>

                    <div className="progress-bar-container">
                        <div
                            className="progress-bar"
                            style={{
                                width: `${(campaign.completed_calls / campaign.total_calls) * 100}%`
                            }}
                        />
                    </div>

                    {campaign.current_call && (
                        <div className="current-call">
                            📞 Calling: {campaign.current_call.phone_number}
                        </div>
                    )}

                    <div className="campaign-status">
                        Status: <span className={`status-badge ${campaign.status}`}>
                            {campaign.status}
                        </span>
                    </div>

                    <div className="campaign-actions">
                        {campaign.status === 'running' && (
                            <button className="stop-btn" onClick={stopCampaign}>
                                ⏹️ Stop Campaign
                            </button>
                        )}
                        {(campaign.status === 'completed' || campaign.status === 'stopped') && (
                            <button className="reset-btn" onClick={resetCampaign}>
                                🔄 Start New Campaign
                            </button>
                        )}
                    </div>
                </div>
            )}

            <style>{`
                .bulk-campaign {
                    background: rgba(255, 255, 255, 0.05);
                    border-radius: 12px;
                    padding: 20px;
                    margin-top: 20px;
                }
                .bulk-campaign h3 {
                    margin: 0 0 20px 0;
                    font-size: 1.2rem;
                }
                .form-group {
                    margin-bottom: 15px;
                }
                .form-group label {
                    display: block;
                    margin-bottom: 5px;
                    font-size: 0.9rem;
                    color: #aaa;
                }
                .form-select, .form-input {
                    width: 100%;
                    padding: 10px;
                    background: #2a2a2a;
                    border: 1px solid #444;
                    border-radius: 8px;
                    color: #fff;
                    font-size: 1rem;
                }
                .form-select option {
                    background: #2a2a2a;
                    color: #fff;
                }
                .variables-info {
                    background: rgba(100, 150, 255, 0.1);
                    border-radius: 8px;
                    padding: 15px;
                    margin: 15px 0;
                }
                .variables-info h4 {
                    margin: 0 0 10px 0;
                    font-size: 0.9rem;
                }
                .variable-chips {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                }
                .chip {
                    padding: 4px 12px;
                    border-radius: 15px;
                    font-size: 0.85rem;
                }
                .chip.required {
                    background: #4caf50;
                    color: white;
                }
                .chip.variable {
                    background: #2196f3;
                    color: white;
                }
                .hint {
                    margin: 10px 0 0 0;
                    font-size: 0.85rem;
                    color: #888;
                }
                .csv-dropzone {
                    border: 2px dashed rgba(255, 255, 255, 0.3);
                    border-radius: 12px;
                    padding: 30px;
                    text-align: center;
                    cursor: pointer;
                    transition: all 0.2s;
                    margin: 15px 0;
                }
                .csv-dropzone:hover, .csv-dropzone.active {
                    border-color: #4caf50;
                    background: rgba(76, 175, 80, 0.1);
                }
                .upload-success {
                    color: #4caf50;
                }
                .csv-preview {
                    margin: 15px 0;
                }
                .csv-preview h4 {
                    margin: 0 0 10px 0;
                    font-size: 0.9rem;
                }
                .preview-table {
                    overflow-x: auto;
                    max-height: 200px;
                }
                .preview-table table {
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 0.85rem;
                }
                .preview-table th, .preview-table td {
                    padding: 8px;
                    text-align: left;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                }
                .preview-table th {
                    background: rgba(255, 255, 255, 0.05);
                }
                .more-row td {
                    color: #888;
                    text-align: center;
                }
                .campaign-settings {
                    margin-top: 20px;
                    padding-top: 20px;
                    border-top: 1px solid rgba(255, 255, 255, 0.1);
                }
                .start-campaign-btn {
                    width: 100%;
                    padding: 15px;
                    background: linear-gradient(135deg, #4caf50, #2196f3);
                    border: none;
                    border-radius: 8px;
                    color: white;
                    font-size: 1.1rem;
                    cursor: pointer;
                    margin-top: 15px;
                }
                .start-campaign-btn:hover {
                    opacity: 0.9;
                }
                .campaign-progress {
                    text-align: center;
                }
                .progress-stats {
                    display: flex;
                    justify-content: center;
                    gap: 30px;
                    margin: 20px 0;
                }
                .stat {
                    text-align: center;
                }
                .stat-value {
                    font-size: 2rem;
                    font-weight: bold;
                    display: block;
                }
                .stat.success .stat-value { color: #4caf50; }
                .stat.error .stat-value { color: #f44336; }
                .stat-label {
                    font-size: 0.85rem;
                    color: #888;
                }
                .progress-bar-container {
                    width: 100%;
                    height: 10px;
                    background: rgba(255, 255, 255, 0.1);
                    border-radius: 5px;
                    overflow: hidden;
                    margin: 20px 0;
                }
                .progress-bar {
                    height: 100%;
                    background: linear-gradient(90deg, #4caf50, #2196f3);
                    transition: width 0.5s;
                }
                .current-call {
                    margin: 15px 0;
                    padding: 10px;
                    background: rgba(33, 150, 243, 0.2);
                    border-radius: 8px;
                    animation: pulse 2s infinite;
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.7; }
                }
                .status-badge {
                    padding: 4px 12px;
                    border-radius: 10px;
                    font-size: 0.85rem;
                }
                .status-badge.running { background: #2196f3; }
                .status-badge.completed { background: #4caf50; }
                .status-badge.stopped { background: #f44336; }
                .status-badge.pending { background: #ff9800; }
                .campaign-actions {
                    margin-top: 20px;
                }
                .stop-btn {
                    padding: 10px 30px;
                    background: #f44336;
                    border: none;
                    border-radius: 8px;
                    color: white;
                    cursor: pointer;
                }
                .reset-btn {
                    padding: 10px 30px;
                    background: #2196f3;
                    border: none;
                    border-radius: 8px;
                    color: white;
                    cursor: pointer;
                }
            `}</style>
        </div>
    );
};

export default BulkCampaign;
