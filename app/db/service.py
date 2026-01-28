"""
Database service for managing call records, transcripts, users, and multi-tenant entities
"""
from datetime import datetime
from typing import List, Optional, Dict, Any
import hashlib
import re
from sqlalchemy.orm import Session
from app.db.models import (
    Organization, Agent, KnowledgeBase,  # Multi-tenant models
    Call, CallTranscript, CallFile, CallMetric, User
)
from app.db.session import SessionLocal


class CallService:
    """Service for managing call records in the database"""
    
    @staticmethod
    def create_call(
        call_provider: str = "websocket",
        provider_call_id: Optional[str] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None  # NEW: Link to handling agent
    ) -> Call:
        """Create a new call record"""
        db = SessionLocal()
        try:
            call = Call(
                agent_id=agent_id,  # NEW
                user_id=user_id,
                call_provider=call_provider,
                provider_call_id=provider_call_id,
                from_number=from_number,
                to_number=to_number,
                start_time=datetime.utcnow()
            )
            db.add(call)
            db.commit()
            db.refresh(call)
            print(f"📞 Call created in DB: {call.id}" + (f" (Agent: {agent_id})" if agent_id else ""))
            return call
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating call: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def end_call(
        call_id: str,
        end_reason: str,
        duration_seconds: Optional[int] = None
    ) -> Optional[Call]:
        """End a call and update its record"""
        db = SessionLocal()
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if call:
                call.end_time = datetime.utcnow()
                call.end_reason = end_reason
                if duration_seconds is not None:
                    call.duration_seconds = duration_seconds
                elif call.start_time:
                    call.duration_seconds = int((call.end_time - call.start_time).total_seconds())
                db.commit()
                db.refresh(call)
                print(f"📴 Call ended in DB: {call.id} - Reason: {end_reason}")
                return call
            return None
        except Exception as e:
            db.rollback()
            print(f"❌ Error ending call: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def save_transcript_content(
        call_id: str,
        transcript_content: str
    ) -> CallTranscript:
        """
        Save the full formatted transcript content as a single record.
        The transcript_content is the entire formatted text (same as .txt file content).
        """
        db = SessionLocal()
        try:
            # Use 'full' as speaker to indicate this is the complete transcript
            transcript = CallTranscript(
                call_id=call_id,
                speaker="full",  # Indicates full transcript, not individual message
                message=transcript_content,
                message_time=datetime.utcnow()
            )
            db.add(transcript)
            db.commit()
            db.refresh(transcript)
            print(f"💾 Full transcript saved to database for call: {call_id}")
            return transcript
        except Exception as e:
            db.rollback()
            print(f"❌ Error saving transcript: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def get_call(call_id: str) -> Optional[Call]:
        """Get a call by ID"""
        db = SessionLocal()
        try:
            return db.query(Call).filter(Call.id == call_id).first()
        finally:
            db.close()
    
    @staticmethod
    def get_call_transcript(call_id: str) -> Optional[str]:
        """Get the full transcript content for a call"""
        db = SessionLocal()
        try:
            transcript = db.query(CallTranscript).filter(
                CallTranscript.call_id == call_id,
                CallTranscript.speaker == "full"
            ).first()
            return transcript.message if transcript else None
        finally:
            db.close()
    
    @staticmethod
    def get_recent_calls(limit: int = 20) -> List[Call]:
        """Get recent calls"""
        db = SessionLocal()
        try:
            return db.query(Call).order_by(Call.created_at.desc()).limit(limit).all()
        finally:
            db.close()
    
    @staticmethod
    def add_file_record(
        call_id: str,
        file_type: str,
        file_path: str
    ) -> CallFile:
        """Add a file record to a call"""
        db = SessionLocal()
        try:
            file_record = CallFile(
                call_id=call_id,
                file_type=file_type,
                file_path=file_path
            )
            db.add(file_record)
            db.commit()
            db.refresh(file_record)
            return file_record
        except Exception as e:
            db.rollback()
            print(f"❌ Error adding file record: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def update_call_status(
        call_id: str,
        status: str
    ) -> Optional[Call]:
        """Update call status"""
        db = SessionLocal()
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if not call:
                # Try to find by provider_call_id
                call = db.query(Call).filter(Call.provider_call_id == call_id).first()
            if call:
                call.status = status
                db.commit()
                db.refresh(call)
                print(f"📊 Call status updated: {call.id} -> {status}")
                return call
            return None
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating call status: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def update_call_phone_numbers(
        call_id: str,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
        provider_call_id: Optional[str] = None
    ) -> Optional[Call]:
        """Update call phone numbers and provider call ID"""
        db = SessionLocal()
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if not call:
                # Try to find by provider_call_id
                call = db.query(Call).filter(Call.provider_call_id == call_id).first()
            if call:
                if from_number:
                    call.from_number = from_number
                if to_number:
                    call.to_number = to_number
                if provider_call_id:
                    call.provider_call_id = provider_call_id
                db.commit()
                db.refresh(call)
                print(f"📞 Call phone numbers updated: {call.id} -> {from_number} -> {to_number}")
                return call
            return None
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating call phone numbers: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def update_call_recording(
        call_id: str,
        recording_url: str,
        recording_id: Optional[str] = None
    ) -> Optional[Call]:
        """Update call recording URL"""
        db = SessionLocal()
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if not call:
                # Try to find by provider_call_id
                call = db.query(Call).filter(Call.provider_call_id == call_id).first()
            if call:
                call.recording_url = recording_url
                if recording_id:
                    call.recording_id = recording_id
                db.commit()
                db.refresh(call)
                print(f"🎙️ Call recording updated: {call.id}")
                return call
            return None
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating call recording: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def update_call_stream(
        call_id: str,
        stream_id: str
    ) -> Optional[Call]:
        """Update call stream ID"""
        db = SessionLocal()
        try:
            call = db.query(Call).filter(Call.id == call_id).first()
            if not call:
                # Try to find by provider_call_id
                call = db.query(Call).filter(Call.provider_call_id == call_id).first()
            if call:
                call.stream_id = stream_id
                db.commit()
                db.refresh(call)
                print(f"📡 Call stream updated: {call.id} -> {stream_id}")
                return call
            return None
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating call stream: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def get_call_by_provider_id(provider_call_id: str) -> Optional[Call]:
        """Get a call by provider call ID"""
        db = SessionLocal()
        try:
            return db.query(Call).filter(Call.provider_call_id == provider_call_id).first()
        finally:
            db.close()
    
    @staticmethod
    def get_calls_with_details(limit: int = 50, organization_id: Optional[str] = None) -> List[dict]:
        """
        Get recent calls with all details including recording URLs.
        
        MULTI-TENANT: If organization_id is provided, only returns calls for agents
        belonging to that organization.
        """
        db = SessionLocal()
        try:
            query = db.query(Call)
            
            # MULTI-TENANT: Filter by organization's agents if provided
            if organization_id:
                # Get all agent IDs for this organization
                from app.db.models import Agent
                org_agent_ids = [a.id for a in db.query(Agent.id).filter(
                    Agent.organization_id == organization_id
                ).all()]
                
                if org_agent_ids:
                    query = query.filter(Call.agent_id.in_(org_agent_ids))
                else:
                    # No agents in org = no calls to return
                    return []
            
            calls = query.order_by(Call.created_at.desc()).limit(limit).all()
            result = []
            for call in calls:
                # Get transcript for this call
                transcript = db.query(CallTranscript).filter(
                    CallTranscript.call_id == call.id,
                    CallTranscript.speaker == "full"
                ).first()
                
                # Get agent name if available
                agent_name = None
                if call.agent:
                    agent_name = call.agent.name
                
                result.append({
                    "id": call.id,
                    "agent_id": call.agent_id,
                    "agent_name": agent_name,  # NEW: Include agent name
                    "provider_call_id": call.provider_call_id,
                    "from_number": call.from_number,
                    "to_number": call.to_number,
                    "start_time": call.start_time.isoformat() if call.start_time else None,
                    "end_time": call.end_time.isoformat() if call.end_time else None,
                    "duration_seconds": call.duration_seconds,
                    "status": call.status or "unknown",
                    "end_reason": call.end_reason,
                    "recording_url": call.recording_url,
                    "recording_id": call.recording_id,
                    "stream_id": call.stream_id,
                    "has_transcript": transcript is not None,
                    "created_at": call.created_at.isoformat() if call.created_at else None
                })
            return result
        finally:
            db.close()


class UserService:
    """Service for managing user accounts in the database"""
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def create_user(
        username: str,
        password: str,
        role: str = "client",
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        organization_id: Optional[str] = None  # NEW: Link user to organization
    ) -> Optional[User]:
        """Create a new user"""
        db = SessionLocal()
        try:
            # Check if username already exists
            existing = db.query(User).filter(User.username == username).first()
            if existing:
                print(f"❌ User '{username}' already exists")
                return None
            
            user = User(
                username=username,
                password_hash=UserService.hash_password(password),
                role=role,
                display_name=display_name or username,
                email=email,
                organization_id=organization_id  # NEW
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"✅ User created: {username} (role: {role}, org: {organization_id})")
            return user
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating user: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def authenticate(username: str, password: str) -> Optional[dict]:
        """Authenticate a user and return user info if successful"""
        db = SessionLocal()
        try:
            user = db.query(User).filter(
                User.username == username,
                User.is_active == True
            ).first()
            
            if not user:
                return None
            
            password_hash = UserService.hash_password(password)
            if user.password_hash != password_hash:
                return None
            
            # Update last login
            user.last_login = datetime.utcnow()
            db.commit()
            
            return {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "display_name": user.display_name,
                "email": user.email,
                "organization_id": user.organization_id  # NEW: Include for multi-tenant
            }
        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return None
        finally:
            db.close()
    
    @staticmethod
    def get_user_by_username(username: str) -> Optional[User]:
        """Get a user by username"""
        db = SessionLocal()
        try:
            return db.query(User).filter(User.username == username).first()
        finally:
            db.close()
    
    @staticmethod
    def get_user_by_id(user_id: str) -> Optional[User]:
        """Get a user by ID"""
        db = SessionLocal()
        try:
            return db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()
    
    @staticmethod
    def get_all_users() -> List[dict]:
        """Get all users"""
        db = SessionLocal()
        try:
            users = db.query(User).order_by(User.created_at.desc()).all()
            return [
                {
                    "id": u.id,
                    "username": u.username,
                    "role": u.role,
                    "display_name": u.display_name,
                    "email": u.email,
                    "is_active": u.is_active,
                    "last_login": u.last_login.isoformat() if u.last_login else None,
                    "created_at": u.created_at.isoformat() if u.created_at else None
                }
                for u in users
            ]
        finally:
            db.close()
    
    @staticmethod
    def update_user(
        user_id: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[User]:
        """Update user details"""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return None
            
            if display_name is not None:
                user.display_name = display_name
            if email is not None:
                user.email = email
            if role is not None:
                user.role = role
            if is_active is not None:
                user.is_active = is_active
            
            db.commit()
            db.refresh(user)
            print(f"✅ User updated: {user.username}")
            return user
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating user: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def update_password(user_id: str, new_password: str) -> bool:
        """Update user password"""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False
            
            user.password_hash = UserService.hash_password(new_password)
            db.commit()
            print(f"✅ Password updated for user: {user.username}")
            return True
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating password: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def delete_user(user_id: str) -> bool:
        """Delete a user"""
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                return False
            
            username = user.username
            db.delete(user)
            db.commit()
            print(f"✅ User deleted: {username}")
            return True
        except Exception as e:
            db.rollback()
            print(f"❌ Error deleting user: {e}")
            return False
        finally:
            db.close()
    
    @staticmethod
    def ensure_admin_exists():
        """Ensure at least one admin user exists (create default if not)"""
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.role == "admin").first()
            if not admin:
                # Create default admin user
                UserService.create_user(
                    username="Agentx",
                    password="Anvenssa@123",
                    role="super_admin",  # Changed from 'admin' to 'super_admin'
                    display_name="AgentX Admin"
                )
                print("✅ Default super admin user created: Agentx")
        finally:
            db.close()


class OrganizationService:
    """Service for managing organizations (client companies)"""
    
    @staticmethod
    def create_organization(
        name: str,
        slug: Optional[str] = None
    ) -> Optional[Organization]:
        """Create a new organization"""
        db = SessionLocal()
        try:
            # Generate slug from name if not provided
            if not slug:
                slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            
            # Check if slug already exists
            existing = db.query(Organization).filter(Organization.slug == slug).first()
            if existing:
                print(f"❌ Organization with slug '{slug}' already exists")
                return None
            
            org = Organization(
                name=name,
                slug=slug,
                is_active=True
            )
            db.add(org)
            db.commit()
            db.refresh(org)
            print(f"✅ Organization created: {name} (slug: {slug})")
            return org
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating organization: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def get_organization(org_id: str) -> Optional[Organization]:
        """Get organization by ID"""
        db = SessionLocal()
        try:
            return db.query(Organization).filter(Organization.id == org_id).first()
        finally:
            db.close()
    
    @staticmethod
    def get_organization_by_slug(slug: str) -> Optional[Organization]:
        """Get organization by slug"""
        db = SessionLocal()
        try:
            return db.query(Organization).filter(Organization.slug == slug).first()
        finally:
            db.close()
    
    @staticmethod
    def get_all_organizations() -> List[dict]:
        """Get all organizations"""
        db = SessionLocal()
        try:
            orgs = db.query(Organization).filter(Organization.is_active == True).order_by(Organization.name).all()
            return [
                {
                    "id": o.id,
                    "name": o.name,
                    "slug": o.slug,
                    "is_active": o.is_active,
                    "created_at": o.created_at.isoformat() if o.created_at else None
                }
                for o in orgs
            ]
        finally:
            db.close()
    
    @staticmethod
    def update_organization(
        org_id: str,
        name: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[Organization]:
        """Update organization"""
        db = SessionLocal()
        try:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if not org:
                return None
            
            if name is not None:
                org.name = name
            if is_active is not None:
                org.is_active = is_active
            
            db.commit()
            db.refresh(org)
            print(f"✅ Organization updated: {org.name}")
            return org
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating organization: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def delete_organization(org_id: str) -> bool:
        """Delete organization (soft delete by setting is_active=False)"""
        db = SessionLocal()
        try:
            org = db.query(Organization).filter(Organization.id == org_id).first()
            if not org:
                return False
            
            org.is_active = False
            db.commit()
            print(f"✅ Organization deactivated: {org.name}")
            return True
        except Exception as e:
            db.rollback()
            print(f"❌ Error deleting organization: {e}")
            return False
        finally:
            db.close()


class AgentService:
    """Service for managing AI voice agents"""
    
    DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant for voice calls. 
Be concise and natural in your responses. 
Ask clarifying questions when needed."""

    @staticmethod
    def create_agent(
        organization_id: str,
        name: str,
        system_prompt: Optional[str] = None,
        phone_number: Optional[str] = None,
        recognition_language: str = "en-IN",
        synthesis_voice_name: str = "en-IN-NeerjaNeural",
        max_call_duration: int = 600,
        max_silence_duration: int = 20,
        description: Optional[str] = None
    ) -> Optional[Agent]:
        """Create a new agent for an organization"""
        db = SessionLocal()
        try:
            # Validate organization exists
            org = db.query(Organization).filter(Organization.id == organization_id).first()
            if not org:
                print(f"❌ Organization not found: {organization_id}")
                return None
            
            # Convert empty phone string to None (avoid unique constraint on '')
            if phone_number == '':
                phone_number = None
            
            # Check if phone number is already in use
            if phone_number:
                existing = db.query(Agent).filter(Agent.phone_number == phone_number).first()
                if existing:
                    print(f"❌ Phone number '{phone_number}' already assigned to another agent")
                    return None
            
            agent = Agent(
                organization_id=organization_id,
                name=name,
                description=description,
                phone_number=phone_number,
                system_prompt=system_prompt or AgentService.DEFAULT_SYSTEM_PROMPT,
                recognition_language=recognition_language,
                synthesis_voice_name=synthesis_voice_name,
                max_call_duration=max_call_duration,
                max_silence_duration=max_silence_duration,
                is_active=True
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            print(f"✅ Agent created: {name} (org: {org.name})")
            return agent
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating agent: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def get_agent(agent_id: str) -> Optional[Agent]:
        """Get agent by ID"""
        db = SessionLocal()
        try:
            return db.query(Agent).filter(Agent.id == agent_id).first()
        finally:
            db.close()
    
    @staticmethod
    def get_agent_by_phone(phone_number: str) -> Optional[Agent]:
        """Get agent by phone number (for routing incoming calls)"""
        db = SessionLocal()
        try:
            return db.query(Agent).filter(
                Agent.phone_number == phone_number,
                Agent.is_active == True
            ).first()
        finally:
            db.close()
    
    @staticmethod
    def get_agents_by_organization(organization_id: str) -> List[dict]:
        """Get all agents for an organization"""
        db = SessionLocal()
        try:
            agents = db.query(Agent).filter(
                Agent.organization_id == organization_id,
                Agent.is_active == True
            ).order_by(Agent.name).all()
            
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "phone_number": a.phone_number,
                    "recognition_language": a.recognition_language,
                    "synthesis_voice_name": a.synthesis_voice_name,
                    "max_call_duration": a.max_call_duration,
                    "max_silence_duration": a.max_silence_duration,
                    "active_kb_id": a.active_kb_id,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None
                }
                for a in agents
            ]
        finally:
            db.close()
    
    @staticmethod
    def get_all_agents() -> List[dict]:
        """Get all agents (super admin only)"""
        db = SessionLocal()
        try:
            agents = db.query(Agent).filter(Agent.is_active == True).order_by(Agent.name).all()
            
            return [
                {
                    "id": a.id,
                    "organization_id": a.organization_id,
                    "name": a.name,
                    "description": a.description,
                    "phone_number": a.phone_number,
                    "recognition_language": a.recognition_language,
                    "synthesis_voice_name": a.synthesis_voice_name,
                    "max_call_duration": a.max_call_duration,
                    "max_silence_duration": a.max_silence_duration,
                    "active_kb_id": a.active_kb_id,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None
                }
                for a in agents
            ]
        finally:
            db.close()
    
    @staticmethod
    def update_agent(
        agent_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        phone_number: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_variables: Optional[str] = None,
        recognition_language: Optional[str] = None,
        synthesis_voice_name: Optional[str] = None,
        max_call_duration: Optional[int] = None,
        max_silence_duration: Optional[int] = None,
        active_kb_id: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[Agent]:
        """Update agent configuration"""
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                return None
            
            # Check unique phone number if changing
            # Convert empty phone string to None
            if phone_number == '':
                phone_number = None
            
            if phone_number is not None and phone_number != agent.phone_number:
                if phone_number:
                    existing = db.query(Agent).filter(Agent.phone_number == phone_number).first()
                    if existing:
                        print(f"❌ Phone number '{phone_number}' already assigned")
                        return None
                agent.phone_number = phone_number
            elif phone_number is None and agent.phone_number:
                # Allow clearing phone number
                agent.phone_number = None
            
            if name is not None: agent.name = name
            if description is not None: agent.description = description
            if system_prompt is not None: agent.system_prompt = system_prompt
            if prompt_variables is not None: agent.prompt_variables = prompt_variables
            if recognition_language is not None: agent.recognition_language = recognition_language
            if synthesis_voice_name is not None: agent.synthesis_voice_name = synthesis_voice_name
            if max_call_duration is not None: agent.max_call_duration = max_call_duration
            if max_silence_duration is not None: agent.max_silence_duration = max_silence_duration
            if active_kb_id is not None: agent.active_kb_id = active_kb_id
            if is_active is not None: agent.is_active = is_active
            
            db.commit()
            db.refresh(agent)
            print(f"✅ Agent updated: {agent.name}")
            return agent
        except Exception as e:
            db.rollback()
            print(f"❌ Error updating agent: {e}")
            raise
        finally:
            db.close()
    
    @staticmethod
    def delete_agent(agent_id: str) -> bool:
        """Delete agent (soft delete)"""
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                return False
            
            agent.is_active = False
            db.commit()
            print(f"✅ Agent deactivated: {agent.name}")
            return True
        except Exception as e:
            db.rollback()
            print(f"❌ Error deleting agent: {e}")
            return False
        finally:
            db.close()
            
    @staticmethod
    def get_agent_config(agent_id: str) -> Optional[dict]:
        """Get flattened configuration for call handling (WebSocket)"""
        db = SessionLocal()
        try:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
            if not agent:
                return None
            
            config = {
                "agent_id": agent.id,
                "agent_name": agent.name,
                "system_prompt": agent.get_resolved_system_prompt(),
                "prompt_variables": agent.get_prompt_variables_dict(),
                "kb_id": agent.active_kb_id,
                "recognition_language": agent.recognition_language,
                "synthesis_voice": agent.synthesis_voice_name,
                "max_call_duration": agent.max_call_duration,
                "max_silence_duration": agent.max_silence_duration
            }
            return config
        finally:
            db.close()


class KnowledgeBaseService:
    """Service for managing knowledge bases"""
    
    @staticmethod
    def create_knowledge_base(
        agent_id: str,
        name: str,
        kb_id: str,  # ChromaDB collection ID
        filename: Optional[str] = None,
        file_path: Optional[str] = None,
        chunk_count: int = 0
    ) -> Optional[KnowledgeBase]:
        """Create a new knowledge base record"""
        db = SessionLocal()
        try:
            kb = KnowledgeBase(
                id=kb_id,  # Use same ID as ChromaDB collection/KB ID
                agent_id=agent_id,
                name=name,
                filename=filename,
                file_path=file_path,
                chunk_count=chunk_count,
                chroma_collection_name=f"kb_{kb_id}",
                is_active=False
            )
            db.add(kb)
            db.commit()
            db.refresh(kb)
            print(f"📚 Knowledge base record created: {name} (Agent: {agent_id})")
            return kb
        except Exception as e:
            db.rollback()
            print(f"❌ Error creating KB record: {e}")
            raise
        finally:
            db.close()

    @staticmethod
    def get_agent_knowledge_bases(agent_id: str) -> List[KnowledgeBase]:
        """Get all knowledge bases for an agent"""
        db = SessionLocal()
        try:
            return db.query(KnowledgeBase).filter(
                KnowledgeBase.agent_id == agent_id
            ).order_by(KnowledgeBase.created_at.desc()).all()
        finally:
            db.close()

    @staticmethod
    def get_knowledge_base(kb_id: str) -> Optional[KnowledgeBase]:
        """Get knowledge base by ID"""
        db = SessionLocal()
        try:
            return db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        finally:
            db.close()
            
    @staticmethod
    def delete_knowledge_base(kb_id: str) -> bool:
        """Delete knowledge base record"""
        db = SessionLocal()
        try:
            kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
            if not kb:
                return False
            
            db.delete(kb)
            db.commit()
            print(f"✅ KB record deleted: {kb.name}")
            return True
        except Exception as e:
            db.rollback()
            print(f"❌ Error deleting KB record: {e}")
            return False
        finally:
            db.close()


# Export services instance (singleton-like usage)
call_service = CallService()
user_service = UserService()
organization_service = OrganizationService()
agent_service = AgentService()
kb_service = KnowledgeBaseService()
