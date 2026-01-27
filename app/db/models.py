"""
Database models for AI Voice Calls
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.db.session import Base


def generate_uuid():
    """Generate a new UUID string"""
    return str(uuid.uuid4())


class Call(Base):
    """Main call record"""
    __tablename__ = "calls"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    call_provider = Column(String(20), nullable=True)  # 'websocket', 'twilio', etc.
    provider_call_id = Column(String(100), nullable=True)
    from_number = Column(String(20), nullable=True)
    to_number = Column(String(20), nullable=True)
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
