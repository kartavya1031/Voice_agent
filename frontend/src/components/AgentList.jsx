
import React, { useState, useEffect } from 'react';

const AgentList = ({ API_URL, onEditAgent, onCreateAgent, addLog, user }) => {
    const [agents, setAgents] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchAgents = async () => {
        setLoading(true);
        try {
            // MULTI-TENANT: Filter by user's organization if they have one
            let url = `${API_URL}/api/agents`;
            if (user?.organizationId) {
                url += `?organization_id=${user.organizationId}`;
            }

            const res = await fetch(url);
            const data = await res.json();
            setAgents(data.agents || []);
        } catch (err) {
            addLog(`Error fetching agents: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchAgents();
    }, [user?.organizationId]);  // Re-fetch when user/org changes

    const deleteAgent = async (agentId, agentName) => {
        if (!confirm(`Are you sure you want to delete agent "${agentName}"?`)) return;

        try {
            const res = await fetch(`${API_URL}/api/agents/${agentId}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            if (data.success) {
                addLog(`✅ Agent "${agentName}" deleted`);
                fetchAgents();
            } else {
                addLog(`❌ Failed to delete agent: ${data.detail}`);
            }
        } catch (err) {
            addLog(`Error deleting agent: ${err.message}`);
        }
    };

    if (loading) return <div className="loading">Loading agents...</div>;

    return (
        <div className="agent-list-container">
            <div className="header-actions">
                <h2>AI Agents</h2>
                <button className="primary-btn" onClick={onCreateAgent}>
                    + New Agent
                </button>
            </div>

            <div className="agents-grid">
                {agents.length === 0 ? (
                    <div className="empty-state">
                        <p>No agents found. Create your first AI agent.</p>
                    </div>
                ) : (
                    agents.map(agent => (
                        <div key={agent.id} className="agent-card">
                            <div className="agent-header">
                                <h3>{agent.name}</h3>
                                <span className={`status-dot ${agent.is_active ? 'active' : 'inactive'}`}></span>
                            </div>
                            <div className="agent-details">
                                <p><strong>Phone:</strong> {agent.phone_number || 'Not assigned'}</p>
                                <p><strong>Voice:</strong> {agent.synthesis_voice_name}</p>
                                <p><strong>Language:</strong> {agent.recognition_language}</p>
                            </div>
                            <div className="agent-actions">
                                <button className="secondary-btn" onClick={() => onEditAgent(agent)}>
                                    Configure
                                </button>
                                <button className="danger-btn icon-only" onClick={() => deleteAgent(agent.id, agent.name)} title="Delete">
                                    🗑️
                                </button>
                            </div>
                        </div>
                    ))
                )}
            </div>

            <style>{`
                .agent-list-container {
                    padding: 20px;
                }
                .header-actions {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 20px;
                }
                .agents-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
                    gap: 20px;
                }
                .agent-card {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                    padding: 20px;
                    display: flex;
                    flex-direction: column;
                    gap: 15px;
                }
                .agent-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                }
                .agent-header h3 {
                    margin: 0;
                    font-size: 1.2rem;
                }
                .status-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    background: #666;
                }
                .status-dot.active {
                    background: #4caf50;
                    box-shadow: 0 0 10px rgba(76, 175, 80, 0.5);
                }
                .agent-details p {
                    margin: 5px 0;
                    font-size: 0.9rem;
                    color: #ccc;
                }
                .agent-actions {
                    display: flex;
                    gap: 10px;
                    margin-top: auto;
                }
                .icon-only {
                    padding: 8px 12px;
                }
            `}</style>
        </div>
    );
};

export default AgentList;
