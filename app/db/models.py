"""
Database models for AI Voice Calls - Multi-Tenant Architecture
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from app.db.session import Base


def generate_uuid():
    """Generate a new UUID string"""
    return str(uuid.uuid4())


# =============================================================================
# MULTI-TENANT MODELS
# =============================================================================

class Organization(Base):
    """
    Organization model for multi-tenant support.
    Each organization (client company) can have multiple users and agents.
    """
    __tablename__ = "organizations"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    slug = Column(String(50), unique=True, nullable=False, index=True)  # URL-friendly identifier
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    users = relationship("User", back_populates="organization")
    agents = relationship("Agent", back_populates="organization")
    
    def __repr__(self):
        return f"<Organization(id={self.id}, name={self.name}, slug={self.slug})>"


class Agent(Base):
    """
    AI Voice Agent configuration.
    Each agent has its own phone number, system prompt, voice settings, and knowledge base.
    """
    __tablename__ = "agents"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Phone number or SIP URI (unique per agent - for routing incoming calls)
    phone_number = Column(String(100), unique=True, nullable=True, index=True)
    
    # Agent Behavior Configuration
    system_prompt = Column(Text, nullable=False)
    prompt_variables = Column(Text, default="{}")  # JSON string for variable substitution
    
    # Knowledge Base
    active_kb_id = Column(String(36), nullable=True)  # ChromaDB collection ID
    
    # Sentiment Analysis Configuration
    # This prompt is used to analyze call transcripts and determine outcomes
    # Example: "Analyze if the user is: 1) Interested in the product 2) Wants a callback 3) Already a customer"
    sentiment_analysis_prompt = Column(Text, nullable=True)
    
    # Speech Settings
    recognition_language = Column(String(10), default="en-IN")
    synthesis_voice_name = Column(String(50), default="en-IN-NeerjaNeural")
    
    # Call Settings
    max_call_duration = Column(Integer, default=600)  # 10 minutes in seconds
    max_silence_duration = Column(Integer, default=20)  # seconds
    
    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="agents")
    calls = relationship("Call", back_populates="agent")
    knowledge_bases = relationship("KnowledgeBase", back_populates="agent")
    
    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, phone={self.phone_number})>"
    
    def get_prompt_variables_dict(self) -> dict:
        """Parse prompt_variables JSON string to dict"""
        import json
        try:
            return json.loads(self.prompt_variables) if self.prompt_variables else {}
        except:
            return {}
    
    def get_resolved_system_prompt(self) -> str:
        """Get system prompt with variables substituted"""
        prompt = self.system_prompt
        variables = self.get_prompt_variables_dict()
        for key, value in variables.items():
            if value:
                prompt = prompt.replace(f"{{{key}}}", str(value))
        return prompt


class KnowledgeBase(Base):
    """
    Knowledge base for RAG (Retrieval Augmented Generation).
    Each agent can have multiple knowledge bases, with one active at a time.
    """
    __tablename__ = "knowledge_bases"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    filename = Column(String(255), nullable=True)  # Original uploaded filename
    file_path = Column(Text, nullable=True)  # Path to stored file
    chunk_count = Column(Integer, default=0)
    chroma_collection_name = Column(String(100), nullable=True)  # ChromaDB collection name
    is_active = Column(Boolean, default=False)  # Only one active per agent
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationships
    agent = relationship("Agent", back_populates="knowledge_bases")
    
    def __repr__(self):
        return f"<KnowledgeBase(id={self.id}, name={self.name}, chunks={self.chunk_count})>"


# =============================================================================
# USER & AUTHENTICATION
# =============================================================================

class User(Base):
    """User model for authentication and access control"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # Store hashed passwords
    role = Column(String(20), nullable=False, default='client')  # 'super_admin', 'org_admin', 'org_member'
    display_name = Column(String(100), nullable=True)
    email = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    last_login = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    organization = relationship("Organization", back_populates="users")
    calls = relationship("Call", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class Call(Base):
    """Main call record"""
    __tablename__ = "calls"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=True, index=True)  # Which agent handled the call
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)  # Link to user who made the call
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=True, index=True)  # Link to bulk campaign
    call_provider = Column(String(20), nullable=True)  # 'websocket', 'twilio', 'frejun'
    provider_call_id = Column(String(100), nullable=True)
    from_number = Column(String(20), nullable=True)
    to_number = Column(String(20), nullable=True)
    contact_name = Column(String(100), nullable=True)  # Optional contact name
    start_time = Column(TIMESTAMP, nullable=True)
    end_time = Column(TIMESTAMP, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    end_reason = Column(String(50), nullable=True)  # 'user_intent', 'silence_timeout', 'max_duration', 'user_hangup'
    status = Column(String(30), default='initiated')  # 'initiated', 'ringing', 'answered', 'completed', 'failed'
    recording_url = Column(Text, nullable=True)  # URL to call recording from FreJun
    recording_id = Column(String(100), nullable=True)  # Recording ID from FreJun
    stream_id = Column(String(100), nullable=True)  # Stream ID from FreJun
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Sentiment Analysis Results
    # sentiment: Brief status like "Interested", "Not Interested", "Callback Requested", etc.
    # sentiment_details: JSON string with full analysis including conditions matched
    sentiment = Column(String(50), nullable=True)
    sentiment_details = Column(Text, nullable=True)  # JSON string with detailed analysis
    
    # Relationships
    agent = relationship("Agent", back_populates="calls")
    user = relationship("User", back_populates="calls")
    transcripts = relationship("CallTranscript", back_populates="call", cascade="all, delete-orphan")
    files = relationship("CallFile", back_populates="call", cascade="all, delete-orphan")
    metrics = relationship("CallMetric", back_populates="call", cascade="all, delete-orphan", uselist=False)
    
    def __repr__(self):
        return f"<Call(id={self.id}, provider={self.call_provider}, duration={self.duration_seconds}s)>"


class CallTranscript(Base):
    """Individual transcript messages"""
    __tablename__ = "call_transcripts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    call_id = Column(String(36), ForeignKey("calls.id"), nullable=False)
    speaker = Column(String(10), nullable=False)  # 'user' or 'agent'
    message = Column(Text, nullable=False)
    message_time = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationship
    call = relationship("Call", back_populates="transcripts")
    
    def __repr__(self):
        return f"<CallTranscript(speaker={self.speaker}, message={self.message[:50]}...)>"


class CallFile(Base):
    """Files associated with a call (recordings, transcripts, etc.)"""
    __tablename__ = "call_files"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    call_id = Column(String(36), ForeignKey("calls.id"), nullable=False)
    file_type = Column(String(20), nullable=False)  # 'transcript', 'recording', 'audio'
    file_path = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationship
    call = relationship("Call", back_populates="files")
    
    def __repr__(self):
        return f"<CallFile(type={self.file_type}, path={self.file_path})>"


class CallMetric(Base):
    """Call metrics and analytics"""
    __tablename__ = "call_metrics"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    call_id = Column(String(36), ForeignKey("calls.id"), nullable=False, unique=True)
    user_speaking_seconds = Column(Integer, default=0)
    agent_speaking_seconds = Column(Integer, default=0)
    silence_seconds = Column(Integer, default=0)
    interruption_count = Column(Integer, default=0)
    
    # Relationship
    call = relationship("Call", back_populates="metrics")
    
    def __repr__(self):
        return f"<CallMetric(call_id={self.call_id}, interruptions={self.interruption_count})>"


# =============================================================================
# BULK CALLING / CAMPAIGN MODELS
# =============================================================================

class Campaign(Base):
    """
    Bulk calling campaign - tracks a batch of calls from CSV upload.
    Each campaign belongs to a user and uses a specific agent.
    """
    __tablename__ = "campaigns"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(36), ForeignKey("agents.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)  # Who started
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    
    # Progress tracking
    total_calls = Column(Integer, default=0)
    completed_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    failed_calls = Column(Integer, default=0)
    
    # Campaign settings
    call_delay_seconds = Column(Integer, default=30)  # Delay between calls (default 30s)
    status = Column(String(20), default='pending')  # pending/running/paused/completed/stopped
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    
    # Relationships
    agent = relationship("Agent")
    user = relationship("User")
    organization = relationship("Organization")
    campaign_calls = relationship("CampaignCall", back_populates="campaign", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Campaign(id={self.id}, name={self.name}, status={self.status})>"


class CampaignCall(Base):
    """
    Individual call within a campaign.
    Tracks status, variables, and links to the actual Call record.
    """
    __tablename__ = "campaign_calls"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=False, index=True)
    
    # Call details
    phone_number = Column(String(20), nullable=False)
    variables = Column(Text, nullable=True)  # JSON string of dynamic prompt variables
    
    # Status tracking
    status = Column(String(20), default='pending')  # pending/calling/completed/failed/retry
    attempt_count = Column(Integer, default=0)  # Number of call attempts
    error_message = Column(Text, nullable=True)  # Error if failed
    
    # Position in queue (for retry logic - failed calls pushed to end)
    queue_position = Column(Integer, default=0)
    
    # Link to actual Call record
    call_id = Column(String(36), ForeignKey("calls.id"), nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    called_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    
    # Relationships
    campaign = relationship("Campaign", back_populates="campaign_calls")
    call = relationship("Call")
    
    def __repr__(self):
        return f"<CampaignCall(id={self.id}, phone={self.phone_number}, status={self.status})>"
    
    def get_variables_dict(self) -> dict:
        """Parse variables JSON string to dict"""
        import json
        try:
            return json.loads(self.variables) if self.variables else {}
        except:
            return {}
