"""
Database service for managing call records and transcripts
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from app.db.models import Call, CallTranscript, CallFile, CallMetric
from app.db.session import SessionLocal


class CallService:
    """Service for managing call records in the database"""
    
    @staticmethod
    def create_call(
        call_provider: str = "websocket",
        provider_call_id: Optional[str] = None,
        from_number: Optional[str] = None,
        to_number: Optional[str] = None
    ) -> Call:
        """Create a new call record"""
        db = SessionLocal()
        try:
            call = Call(
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


# Singleton instance
call_service = CallService()
