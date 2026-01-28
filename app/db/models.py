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
    
    # Phone number (unique per agent - for routing incoming calls)
    phone_number = Column(String(20), unique=True, nullable=True, index=True)
    
    # Agent Behavior Configuration
    system_prompt = Column(Text, nullable=False)
    prompt_variables = Column(Text, default="{}")  # JSON string for variable substitution
    
    # Knowledge Base
    active_kb_id = Column(String(36), nullable=True)  # ChromaDB collection ID
    
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

