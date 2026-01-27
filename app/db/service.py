"""
Database service for managing call records, transcripts, and users
"""
from datetime import datetime
from typing import List, Optional
import hashlib
from sqlalchemy.orm import Session
from app.db.models import Call, CallTranscript, CallFile, CallMetric, User
from app.db.session import SessionLocal


class CallService:
    """Service for managing call records in the database"""
    
    @staticmethod
    def create_call(
        call_provider: str = "websocket",
        provider_call_id: Optional[str] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Call:
        """Create a new call record"""
        db = SessionLocal()
        try:
            call = Call(
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
            print(f"📞 Call created in DB: {call.id}")
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
    def get_calls_with_details(limit: int = 50) -> List[dict]:
        """Get recent calls with all details including recording URLs"""
        db = SessionLocal()
        try:
            calls = db.query(Call).order_by(Call.created_at.desc()).limit(limit).all()
            result = []
            for call in calls:
                # Get transcript for this call
                transcript = db.query(CallTranscript).filter(
                    CallTranscript.call_id == call.id,
                    CallTranscript.speaker == "full"
                ).first()
                
                result.append({
                    "id": call.id,
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
        email: Optional[str] = None
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
                email=email
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"✅ User created: {username} (role: {role})")
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
                "email": user.email
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
                    role="admin",
                    display_name="AgentX Admin"
                )
                print("✅ Default admin user created: Agentx")
        finally:
            db.close()


# Singleton instances
call_service = CallService()
user_service = UserService()

