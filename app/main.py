import warnings
# Suppress SQLAlchemy warnings that cause uvicorn to think startup failed
warnings.filterwarnings("ignore", category=UserWarning, module="sqlalchemy")
warnings.filterwarnings("ignore", message=".*Background on this error.*")

from fastapi import FastAPI, WebSocket, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import base64
import asyncio
import threading
import queue
import re
import json
import time
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List

# Global turn tracking for barge-in support (kept for FreJun handler backward compat)
current_turn_id = 0
current_turn_lock = threading.Lock()

from app.services.llm import (
    ask_ai, ask_ai_streaming, ask_ai_streaming_for_agent,
    reset_conversation, add_to_conversation, clean_llm_output,
)
from app.services.speech import (
    text_to_speech,
    text_to_speech_streaming,
    text_to_speech_streaming_for_agent,
    text_to_speech_telephony,
    text_to_speech_telephony_for_agent,
    create_streaming_recognizer,
    create_streaming_recognizer_for_agent,
    update_speech_settings,
    get_current_speech_settings
)
from app.services.vector_store import (
    set_active_knowledge_base,
    create_knowledge_base_from_text,
    delete_knowledge_base as delete_kb_collection,
    get_active_kb_info,
    get_kb_file_path,
    KB_FILES_DIR
)
from app.services.agent_config import agent_config_service
from app.db.service import call_service
from app.api.frejun import router as frejun_router
from app.api.webhooks import router as webhooks_router
from app.api.auth import router as auth_router
from app.api.agents import router as agents_router
from app.api.campaigns import router as campaigns_router  # NEW: Bulk calling campaigns

app = FastAPI(title="Anvenssa Voice Agent API")

# Include API routers
app.include_router(frejun_router)
app.include_router(webhooks_router)
app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(campaigns_router)  # NEW: Bulk calling

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize speech settings from saved config on startup
@app.on_event("startup")
def startup_event():
    """Initialize settings from saved config"""
    # Initialize database
    from app.db.session import init_db
    init_db()
    
    speech_settings = agent_config_service.get_speech_settings()
    update_speech_settings(
        recognition_language=speech_settings.recognition_language,
        synthesis_voice=speech_settings.synthesis_voice_name
    )
    
    # Set active knowledge base if configured
    active_kb = agent_config_service.get_active_knowledge_base()
    if active_kb:
        set_active_knowledge_base(active_kb.id)
        print(f"📚 Loaded active knowledge base: {active_kb.name}")
    
    print(f"🗣️ Speech settings loaded: lang={speech_settings.recognition_language}, voice={speech_settings.synthesis_voice_name}")
    
    # Pre-initialize Azure Speech services to avoid race conditions during first call
    # Error 2176 can occur when STT and TTS are initialized concurrently
    from app.services.speech import initialize_speech_services
    initialize_speech_services()

# Configurable Call Settings (can be changed via API)
class CallSettings:
    max_call_duration: int = 10 * 60  # 10 minutes default
    max_silence_duration: int = 20  # 20 seconds default

settings = CallSettings()

# Pydantic models for API
class SettingsUpdate(BaseModel):
    max_call_duration: Optional[int] = None
    max_silence_duration: Optional[int] = None

class SettingsResponse(BaseModel):
    max_call_duration: int
    max_silence_duration: int


# Agent Configuration Pydantic Models
class SpeechSettingsUpdate(BaseModel):
    recognition_language: Optional[str] = None
    synthesis_voice_name: Optional[str] = None

class SpeechSettingsResponse(BaseModel):
    recognition_language: str
    synthesis_voice_name: str

class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    filename: str
    created_at: str
    chunk_count: int

class AgentConfigResponse(BaseModel):
    speech_settings: SpeechSettingsResponse
    active_knowledge_base_id: Optional[str]
    knowledge_bases: List[KnowledgeBaseResponse]

class SystemPromptUpdate(BaseModel):
    system_prompt: str

class SystemPromptResponse(BaseModel):
    system_prompt: str

class PromptVariablesUpdate(BaseModel):
    variables: dict


# API Endpoints
@app.get("/api/settings", response_model=SettingsResponse)
def get_settings():
    """Get current call settings"""
    return {
        "max_call_duration": settings.max_call_duration,
        "max_silence_duration": settings.max_silence_duration
    }

@app.post("/api/settings", response_model=SettingsResponse)
def update_settings(update: SettingsUpdate):
    """Update call settings"""
    if update.max_call_duration is not None:
        settings.max_call_duration = update.max_call_duration
    if update.max_silence_duration is not None:
        settings.max_silence_duration = update.max_silence_duration
    print(f"⚙️ Settings updated: duration={settings.max_call_duration}s, silence={settings.max_silence_duration}s")
    return {
        "max_call_duration": settings.max_call_duration,
        "max_silence_duration": settings.max_silence_duration
    }


# Database API Endpoints
@app.get("/api/calls")
def list_calls():
    """List recent calls from database"""
    try:
        calls = call_service.get_recent_calls(limit=50)
        return {
            "calls": [
                {
                    "id": c.id,
                    "provider": c.call_provider,
                    "from_number": c.from_number,
                    "to_number": c.to_number,
                    "start_time": c.start_time.isoformat() if c.start_time else None,
                    "end_time": c.end_time.isoformat() if c.end_time else None,
                    "duration": c.duration_seconds,
                    "status": getattr(c, 'status', None) or c.end_reason or "unknown",
                    "end_reason": c.end_reason,
                    "recording_url": getattr(c, 'recording_url', None),
                    "recording_id": getattr(c, 'recording_id', None)
                }
                for c in calls
            ]
        }
    except Exception as e:
        return {"error": str(e), "calls": []}


@app.get("/api/calls/history")
def get_call_history(organization_id: Optional[str] = None, user_id: Optional[str] = None):
    """
    Get call history with full details including recordings and transcripts.
    
    MULTI-TENANT: 
    - If organization_id is provided, only returns calls for agents belonging to that organization.
    - If user_id is provided, only returns calls initiated by that user.
    - Both can be combined for stricter filtering.
    """
    try:
        calls = call_service.get_calls_with_details(limit=50, organization_id=organization_id, user_id=user_id)
        return {"calls": calls, "total": len(calls)}
    except Exception as e:
        return {"error": str(e), "calls": [], "total": 0}


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    """Get a specific call with its transcript"""
    try:
        call = call_service.get_call(call_id)
        if not call:
            return {"error": "Call not found"}
        
        # Get full transcript content
        transcript_content = call_service.get_call_transcript(call_id)
        
        return {
            "id": call.id,
            "provider": call.call_provider,
            "from_number": call.from_number,
            "to_number": call.to_number,
            "start_time": call.start_time.isoformat() if call.start_time else None,
            "end_time": call.end_time.isoformat() if call.end_time else None,
            "duration": call.duration_seconds,
            "status": getattr(call, 'status', None) or call.end_reason or "unknown",
            "end_reason": call.end_reason,
            "recording_url": getattr(call, 'recording_url', None),
            "recording_id": getattr(call, 'recording_id', None),
            "sentiment": getattr(call, 'sentiment', None),
            "sentiment_details": getattr(call, 'sentiment_details', None),
            "transcript": transcript_content
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/calls/{call_id}/analyze-sentiment")
def analyze_call_sentiment_endpoint(call_id: str):
    """
    Manually trigger sentiment analysis for a specific call.
    Useful for re-analyzing calls or analyzing calls that were made before sentiment was enabled.
    """
    try:
        # Get call and transcript
        call = call_service.get_call(call_id)
        if not call:
            return {"error": "Call not found"}
        
        transcript_content = call_service.get_call_transcript(call_id)
        if not transcript_content:
            return {"error": "No transcript found for this call"}
        
        # Run sentiment analysis
        from app.services.sentiment_analysis import analyze_and_save_sentiment
        result = analyze_and_save_sentiment(call_id, transcript_content, call.agent_id)
        
        return {
            "success": True,
            "call_id": call_id,
            "sentiment": result.get("sentiment"),
            "details": result
        }
    except Exception as e:
        return {"error": str(e), "success": False}


@app.get("/api/calls/{call_id}/recording")
async def get_call_recording(call_id: str):
    """
    Proxy endpoint to serve call recordings.
    This avoids CORS issues when playing recordings from FreJun.
    """
    from fastapi.responses import StreamingResponse
    import httpx
    
    try:
        call = call_service.get_call(call_id)
        if not call:
            return {"error": "Call not found"}
        
        recording_url = getattr(call, 'recording_url', None)
        if not recording_url:
            return {"error": "No recording available for this call"}
        
        # Fetch the recording from FreJun (requires API key authentication)
        frejun_api_key = os.getenv("FREJUN_API_KEY", "")
        headers = {}
        if frejun_api_key and "frejun.ai" in recording_url:
            headers["x-api-key"] = frejun_api_key
        
        async with httpx.AsyncClient() as client:
            response = await client.get(recording_url, headers=headers, follow_redirects=True, timeout=30.0)
            
            if response.status_code != 200:
                return {"error": f"Failed to fetch recording: {response.status_code}"}
            
            # Return the audio file as a streaming response
            content_type = response.headers.get("content-type", "audio/wav")
            
            return StreamingResponse(
                iter([response.content]),
                media_type=content_type,
                headers={
                    "Content-Disposition": f'inline; filename="recording_{call_id}.wav"',
                    "Accept-Ranges": "bytes"
                }
            )
    except Exception as e:
        print(f"❌ Error fetching recording: {e}")
        return {"error": str(e)}


# ============================================
# Agent Configuration API Endpoints
# ============================================

@app.get("/api/agent/config")
def get_agent_config():
    """Get complete agent configuration"""
    speech = agent_config_service.get_speech_settings()
    kbs = agent_config_service.get_knowledge_bases()
    
    return {
        "speech_settings": {
            "recognition_language": speech.recognition_language,
            "synthesis_voice_name": speech.synthesis_voice_name
        },
        "system_prompt": agent_config_service.get_system_prompt(),
        "active_knowledge_base_id": agent_config_service.config.active_knowledge_base_id,
        "knowledge_bases": [
            {
                "id": kb.id,
                "name": kb.name,
                "filename": kb.filename,
                "created_at": kb.created_at,
                "chunk_count": kb.chunk_count
            }
            for kb in kbs
        ],
        "prompt_variables": agent_config_service.get_prompt_variables(),
        "detected_variables": agent_config_service.get_detected_variables()
    }


@app.get("/api/agent/system-prompt")
def get_system_prompt():
    """Get current system prompt"""
    return {
        "system_prompt": agent_config_service.get_system_prompt()
    }


@app.post("/api/agent/system-prompt")
def update_system_prompt(update: SystemPromptUpdate):
    """Update system prompt"""
    prompt = agent_config_service.update_system_prompt(update.system_prompt)
    print(f"📝 System prompt updated ({len(prompt)} chars)")
    return {
        "system_prompt": prompt
    }


@app.post("/api/agent/system-prompt/reset")
def reset_system_prompt():
    """Reset system prompt to default"""
    prompt = agent_config_service.reset_system_prompt()
    print("📝 System prompt reset to default")
    return {
        "system_prompt": prompt,
        "prompt_variables": {},
        "detected_variables": agent_config_service.get_detected_variables()
    }


@app.get("/api/agent/prompt-variables")
def get_prompt_variables():
    """Get current prompt variables and detected variable names"""
    return {
        "variables": agent_config_service.get_prompt_variables(),
        "detected_variables": agent_config_service.get_detected_variables()
    }


@app.post("/api/agent/prompt-variables")
def update_prompt_variables(update: PromptVariablesUpdate):
    """Update prompt variable values"""
    variables = agent_config_service.update_prompt_variables(update.variables)
    print(f"📝 Prompt variables updated: {list(variables.keys())}")
    return {
        "variables": variables,
        "detected_variables": agent_config_service.get_detected_variables()
    }


@app.get("/api/agent/speech")
def get_speech_settings():
    """Get current speech settings"""
    speech = agent_config_service.get_speech_settings()
    return {
        "recognition_language": speech.recognition_language,
        "synthesis_voice_name": speech.synthesis_voice_name
    }


@app.post("/api/agent/speech")
def update_speech_settings_api(update: SpeechSettingsUpdate):
    """Update speech settings"""
    # Update config service
    speech = agent_config_service.update_speech_settings(
        recognition_language=update.recognition_language,
        synthesis_voice_name=update.synthesis_voice_name
    )
    
    # Update runtime speech service
    update_speech_settings(
        recognition_language=update.recognition_language,
        synthesis_voice=update.synthesis_voice_name
    )
    
    print(f"🗣️ Speech settings updated: lang={speech.recognition_language}, voice={speech.synthesis_voice_name}")
    
    return {
        "recognition_language": speech.recognition_language,
        "synthesis_voice_name": speech.synthesis_voice_name
    }


@app.get("/api/agent/knowledge-bases")
def list_knowledge_bases():
    """List all knowledge bases"""
    kbs = agent_config_service.get_knowledge_bases()
    active_id = agent_config_service.config.active_knowledge_base_id
    
    return {
        "knowledge_bases": [
            {
                "id": kb.id,
                "name": kb.name,
                "filename": kb.filename,
                "created_at": kb.created_at,
                "chunk_count": kb.chunk_count,
                "is_active": kb.id == active_id
            }
            for kb in kbs
        ],
        "active_id": active_id
    }


@app.post("/api/agent/knowledge-bases")
async def create_knowledge_base(
    file: UploadFile = File(...),
    name: str = Form(...)
):
    """Upload a PDF/TXT file and create a new knowledge base"""
    print(f"📥 KB Upload started: name='{name}', file='{file.filename}'")
    try:
        # Generate unique ID
        kb_id = str(uuid.uuid4())[:8]
        print(f"   Generated KB ID: {kb_id}")
       
        # Read file content
        content = await file.read()
        filename = file.filename or "uploaded_file"
        print(f"   File read: {len(content)} bytes")
       
        # Save the original file
        file_path = get_kb_file_path(kb_id, filename)
        with open(file_path, 'wb') as f:
            f.write(content)
        print(f"   File saved to: {file_path}")
       
        # Extract text based on file type
        text_content = ""
        if filename.lower().endswith('.pdf'):
            print(f"   Processing PDF...")
            try:
                import fitz  # PyMuPDF
                pdf_doc = fitz.open(stream=content, filetype="pdf")
                for page in pdf_doc:
                    text_content += page.get_text()
                pdf_doc.close()
                print(f"   PDF text extracted: {len(text_content)} chars")
            except ImportError:
                print(f"   PyMuPDF not available, trying pdfplumber...")
                # Fallback: try with pdfplumber
                try:
                    import pdfplumber
                    import io
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        for page in pdf.pages:
                            text_content += page.extract_text() or ""
                    print(f"   pdfplumber text extracted: {len(text_content)} chars")
                except ImportError:
                    print(f"   ❌ No PDF library available!")
                    return {"error": "PDF processing library not installed. Install pymupdf or pdfplumber."}
        elif filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
            text_content = content.decode('utf-8', errors='ignore')
            print(f"   Text file decoded: {len(text_content)} chars")
        else:
            print(f"   ❌ Unsupported file type: {filename}")
            return {"error": f"Unsupported file type: {filename}. Supported: .pdf, .txt, .md"}
       
        if not text_content.strip():
            print(f"   ❌ No text content extracted from file!")
            return {"error": "Could not extract text from file"}
       
        print(f"   Creating vector store collection...")
        # Create knowledge base in vector store
        chunk_count = create_knowledge_base_from_text(kb_id, name, text_content)
        print(f"   Vector store created with {chunk_count} chunks")
       
        print(f"   Saving to agent config...")
        # Save to config
        kb = agent_config_service.add_knowledge_base(
            kb_id=kb_id,
            name=name,
            filename=filename,
            chunk_count=chunk_count
        )
       
        print(f"📚 ✅ Created knowledge base: {name} ({kb_id}) with {chunk_count} chunks")
       
        return {
            "success": True,
            "knowledge_base": {
                "id": kb.id,
                "name": kb.name,
                "filename": kb.filename,
                "created_at": kb.created_at,
                "chunk_count": kb.chunk_count
            }
        }
       
    except Exception as e:
        import traceback
        print(f"   ❌ Exception in create_knowledge_base: {e}")
        traceback.print_exc()
        return {"error": str(e)}
        return {
            "success": True,
            "knowledge_base": {
                "id": kb.id,
                "name": kb.name,
                "filename": kb.filename,
                "created_at": kb.created_at,
                "chunk_count": kb.chunk_count
            }
        }
       
    except Exception as e:
        import traceback
        print(f"   ❌ Exception in create_knowledge_base: {e}")
        traceback.print_exc()
        return {"error": str(e)}
        
@app.post("/api/agent/knowledge-bases/{kb_id}/activate")
def activate_knowledge_base(kb_id: str):
    """Activate a specific knowledge base"""
    # Verify KB exists
    kbs = agent_config_service.get_knowledge_bases()
    kb_exists = any(kb.id == kb_id for kb in kbs)
    
    if not kb_exists:
        print(f"📚 ❌ Knowledge base not found: {kb_id}")
        return {"error": "Knowledge base not found"}
    
    # Set active in config (persists)
    agent_config_service.set_active_knowledge_base(kb_id)
    
    # Set active in vector store (runtime)
    set_active_knowledge_base(kb_id)
    
    print(f"📚 ✅ Activated knowledge base: {kb_id}")
    return {"success": True, "active_id": kb_id}


@app.post("/api/agent/knowledge-bases/deactivate")
def deactivate_knowledge_base():
    """Deactivate custom knowledge base, use default"""
    agent_config_service.set_active_knowledge_base(None)
    set_active_knowledge_base(None)
    print("📚 Deactivated custom knowledge base, using default")
    return {"success": True, "active_id": None}


@app.delete("/api/agent/knowledge-bases/{kb_id}")
def delete_knowledge_base(kb_id: str):
    """Delete a knowledge base"""
    # Delete from vector store
    delete_kb_collection(kb_id)
    
    # Get file info before deleting config
    kbs = agent_config_service.get_knowledge_bases()
    file_to_delete = None
    for kb in kbs:
        if kb.id == kb_id:
            file_to_delete = get_kb_file_path(kb_id, kb.filename)
            break
    
    # Delete from config
    success = agent_config_service.delete_knowledge_base(kb_id)
    
    # Delete the file
    if file_to_delete and file_to_delete.exists():
        try:
            file_to_delete.unlink()
        except:
            pass
    
    if success:
        print(f"🗑️ Deleted knowledge base: {kb_id}")
        return {"success": True}
    else:
        return {"error": "Knowledge base not found"}


@app.get("/api/agent/voices")
def get_available_voices():
    """Get list of available Azure Speech voices"""
    # Common Azure voices for different languages
    # Added more natural-sounding and conversational voices
    # Voice data includes both old fields (id, name, language) and new fields
    # (shortName, localName, gender, locale) for frontend compatibility
    voices = [
        # English - India (Most Natural)
        {"id": "en-IN-NeerjaNeural", "shortName": "en-IN-NeerjaNeural", "localName": "Neerja (Indian English, Female) ⭐ Recommended", "name": "Neerja", "gender": "Female", "locale": "en-IN", "language": "en-IN"},
        {"id": "en-IN-PrabhatNeural", "shortName": "en-IN-PrabhatNeural", "localName": "Prabhat (Indian English, Male)", "name": "Prabhat", "gender": "Male", "locale": "en-IN", "language": "en-IN"},
        # English - US (Very Natural)
        {"id": "en-US-JennyNeural", "shortName": "en-US-JennyNeural", "localName": "Jenny (US English, Female) ⭐ Very Natural", "name": "Jenny", "gender": "Female", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-JennyMultilingualNeural", "shortName": "en-US-JennyMultilingualNeural", "localName": "Jenny Multilingual (US, Female) ⭐ Most Natural", "name": "Jenny Multilingual", "gender": "Female", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-GuyNeural", "shortName": "en-US-GuyNeural", "localName": "Guy (US English, Male)", "name": "Guy", "gender": "Male", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-AriaNeural", "shortName": "en-US-AriaNeural", "localName": "Aria (US English, Female) ⭐ Conversational", "name": "Aria", "gender": "Female", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-DavisNeural", "shortName": "en-US-DavisNeural", "localName": "Davis (US English, Male) ⭐ Warm", "name": "Davis", "gender": "Male", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-JasonNeural", "shortName": "en-US-JasonNeural", "localName": "Jason (US English, Male)", "name": "Jason", "gender": "Male", "locale": "en-US", "language": "en-US"},
        {"id": "en-US-SaraNeural", "shortName": "en-US-SaraNeural", "localName": "Sara (US English, Female)", "name": "Sara", "gender": "Female", "locale": "en-US", "language": "en-US"},
        # English - UK
        {"id": "en-GB-SoniaNeural", "shortName": "en-GB-SoniaNeural", "localName": "Sonia (British English, Female)", "name": "Sonia", "gender": "Female", "locale": "en-GB", "language": "en-GB"},
        {"id": "en-GB-RyanNeural", "shortName": "en-GB-RyanNeural", "localName": "Ryan (British English, Male)", "name": "Ryan", "gender": "Male", "locale": "en-GB", "language": "en-GB"},
        # Hindi
        {"id": "hi-IN-SwaraNeural", "shortName": "hi-IN-SwaraNeural", "localName": "Swara (Hindi, Female)", "name": "Swara", "gender": "Female", "locale": "hi-IN", "language": "hi-IN"},
        {"id": "hi-IN-MadhurNeural", "shortName": "hi-IN-MadhurNeural", "localName": "Madhur (Hindi, Male)", "name": "Madhur", "gender": "Male", "locale": "hi-IN", "language": "hi-IN"},
        {"id": "hi-IN-AartiNeural", "shortName": "hi-IN-AartiNeural", "localName": "Aarti (Hindi, Female)", "name": "Aarti", "gender": "Female", "locale": "hi-IN", "language": "hi-IN"},
        {"id": "hi-IN-KavyaNeural", "shortName": "hi-IN-KavyaNeural", "localName": "Kavya (Hindi, Female)", "name": "Kavya", "gender": "Female", "locale": "hi-IN", "language": "hi-IN"},
        # Spanish
        {"id": "es-ES-ElviraNeural", "shortName": "es-ES-ElviraNeural", "localName": "Elvira (Spanish, Female)", "name": "Elvira", "gender": "Female", "locale": "es-ES", "language": "es-ES"},
        {"id": "es-MX-DaliaNeural", "shortName": "es-MX-DaliaNeural", "localName": "Dalia (Mexican Spanish, Female)", "name": "Dalia", "gender": "Female", "locale": "es-MX", "language": "es-MX"},
        # French
        {"id": "fr-FR-DeniseNeural", "shortName": "fr-FR-DeniseNeural", "localName": "Denise (French, Female)", "name": "Denise", "gender": "Female", "locale": "fr-FR", "language": "fr-FR"},
        # German
        {"id": "de-DE-KatjaNeural", "shortName": "de-DE-KatjaNeural", "localName": "Katja (German, Female)", "name": "Katja", "gender": "Female", "locale": "de-DE", "language": "de-DE"},
        # Japanese
        {"id": "ja-JP-NanamiNeural", "shortName": "ja-JP-NanamiNeural", "localName": "Nanami (Japanese, Female)", "name": "Nanami", "gender": "Female", "locale": "ja-JP", "language": "ja-JP"},
        # Chinese
        {"id": "zh-CN-XiaoxiaoNeural", "shortName": "zh-CN-XiaoxiaoNeural", "localName": "Xiaoxiao (Chinese, Female)", "name": "Xiaoxiao", "gender": "Female", "locale": "zh-CN", "language": "zh-CN"},
    ]
    
    languages = [
        {"id": "en-IN", "code": "en-IN", "name": "English (India)"},
        {"id": "en-US", "code": "en-US", "name": "English (US)"},
        {"id": "en-GB", "code": "en-GB", "name": "English (UK)"},
        {"id": "hi-IN", "code": "hi-IN", "name": "Hindi (India)"},
        {"id": "es-ES", "code": "es-ES", "name": "Spanish (Spain)"},
        {"id": "es-MX", "code": "es-MX", "name": "Spanish (Mexico)"},
        {"id": "fr-FR", "code": "fr-FR", "name": "French (France)"},
        {"id": "de-DE", "code": "de-DE", "name": "German (Germany)"},
        {"id": "ja-JP", "code": "ja-JP", "name": "Japanese (Japan)"},
        {"id": "zh-CN", "code": "zh-CN", "name": "Chinese (Mainland)"},
    ]
    
    return {"voices": voices, "languages": languages}

# Keywords that indicate user wants to end call
END_CALL_KEYWORDS = [
    "bye", "goodbye", "bye bye", "good bye",
    "thank you", "thanks", "धन्यवाद", "આભાર",
    "done", "that's all", "nothing else",
    "end call", "disconnect", "hang up"
]


def detect_end_intent_simple(text: str) -> bool:
    """Simple keyword-based end intent detection"""
    text_lower = text.lower().strip()
    
    for keyword in END_CALL_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def detect_end_intent_llm(text: str, conversation_context: str) -> bool:
    """Use LLM to detect if user wants to end the call"""
    from openai import AzureOpenAI
    from app.core.config import AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, DEPLOYMENT_NAME
    
    client = AzureOpenAI(
        api_key=AZURE_OPENAI_KEY,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version="2024-02-15-preview"
    )
    
    prompt = f"""Analyze if the user wants to END the conversation based on their message.
    
User's latest message: "{text}"
Recent conversation context: {conversation_context[-500:] if len(conversation_context) > 500 else conversation_context}

Reply with ONLY "END" if the user clearly wants to end/conclude the conversation.
Reply with ONLY "CONTINUE" if the conversation should continue.

Your response (END or CONTINUE):"""

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0
        )
        result = response.choices[0].message.content.strip().upper()
        return "END" in result
    except Exception as e:
        print(f"   ⚠️ Intent detection error: {e}")
        return False


def save_transcript(transcript: list, call_duration: float, call_id: str = None, end_reason: str = None, agent_id: str = None):
    """Save call transcript to database and trigger sentiment analysis"""
    
    # Format transcript content
    content = []
    content.append("=" * 60)
    content.append(f"CALL TRANSCRIPT")
    content.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append(f"Duration: {call_duration:.1f} seconds")
    if call_id:
        content.append(f"Call ID: {call_id}")
    content.append("=" * 60)
    content.append("")
    
    for entry in transcript:
        role = entry["role"].upper()
        text = entry["text"]
        ts = entry.get("timestamp", "")
        content.append(f"[{ts}] {role}:")
        content.append(f"  {text}")
        content.append("")
    
    content.append("=" * 60)
    content.append("END OF TRANSCRIPT")
    content.append("=" * 60)
    
    # Join content into single string
    transcript_content = "\n".join(content)
    
    # Save to database
    if call_id:
        try:
            # Save the full formatted transcript content to database
            call_service.save_transcript_content(call_id, transcript_content)
            
            # Update call end info
            call_service.end_call(
                call_id=call_id,
                end_reason=end_reason or "unknown",
                duration_seconds=int(call_duration)
            )
            
            print(f"💾 Transcript saved to database: {call_id}")
            
            # Trigger sentiment analysis in background
            # Get agent_id from call if not provided
            if not agent_id:
                call = call_service.get_call(call_id)
                if call:
                    agent_id = call.agent_id
            
            # Run sentiment analysis if we have a transcript with content
            if transcript_content and len(transcript) > 0:
                try:
                    from app.services.sentiment_analysis import analyze_and_save_sentiment
                    print(f"🎯 Starting sentiment analysis for call {call_id}...")
                    analyze_and_save_sentiment(call_id, transcript_content, agent_id)
                except Exception as e:
                    print(f"⚠️ Sentiment analysis failed: {e}")
            
        except Exception as e:
            print(f"⚠️ Could not save to database: {e}")
    else:
        print("⚠️ No call_id provided, transcript not saved")
    
    return call_id


@app.get("/")
def health():
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket, agent_id: str = None, user_id: str = None):
    """
    Browser-based audio WebSocket.
    
    MULTI-TENANT: Accepts agent_id and user_id query parameters.
    - agent_id: Load agent-specific config (prompt, voice, KB)
    - user_id: Track which user initiated the call
    
    CONCURRENCY-SAFE: All state is per-connection. No global mutation.
    Each WebSocket connection has its own:
    - agent_config (prompt, voice, KB)
    - conversation history
    - turn tracking (for barge-in)
    - STT recognizer
    """
    # Per-call turn tracking (NOT global - allows concurrent calls)
    call_turn_id = [0]
    call_turn_lock = threading.Lock()
    
    # =========================================================================
    # MULTI-TENANT: Parse parameters from query string
    # =========================================================================
    if agent_id is None:
        agent_id = ws.query_params.get("agent_id")
    if user_id is None:
        user_id = ws.query_params.get("user_id")
    
    # Agent-specific configuration (defaults to global settings)
    agent_config = {
        "system_prompt": None,  # Will use default if None
        "kb_id": None,  # Knowledge base ID
        "recognition_language": "en-IN",
        "synthesis_voice": "en-IN-NeerjaNeural",
        "agent_name": "Default Agent",
        "max_call_duration": 10 * 60,  # 10 minutes
        "max_silence_duration": 20,  # 20 seconds
    }
    
    if agent_id:
        try:
            from app.db.service import agent_service
            agent = agent_service.get_agent(agent_id)
            if agent:
                print(f"   🤖 Browser call - Loading agent: {agent.name} (ID: {agent_id})")
                agent_config["agent_name"] = agent.name
                agent_config["system_prompt"] = agent.get_resolved_system_prompt()  # Use resolved prompt with variables
                agent_config["kb_id"] = agent.active_kb_id
                agent_config["recognition_language"] = agent.recognition_language or "en-IN"
                agent_config["synthesis_voice"] = agent.synthesis_voice_name or "en-IN-NeerjaNeural"
                agent_config["max_call_duration"] = agent.max_call_duration or 600
                agent_config["max_silence_duration"] = agent.max_silence_duration or 20
                print(f"   📚 KB: {agent_config['kb_id']}, Voice: {agent_config['synthesis_voice']}")
            else:
                print(f"   ⚠️ Agent {agent_id} not found, using defaults")
        except Exception as e:
            print(f"   ⚠️ Error loading agent config: {e}")
    else:
        print(f"   ℹ️ Browser call - No agent_id provided, using default configuration")
    
    # Agent-specific conversation history (not global!)
    agent_conversation_history = []
    
    await ws.accept()
    print(f"🔗 Browser WebSocket connected (Agent: {agent_config['agent_name']})")

    loop = asyncio.get_running_loop()
    
    # Call state
    call_start_time = time.time()
    last_activity_time = time.time()
    last_playback_complete_time = [None]  # Track when CLIENT finishes playing audio
    is_agent_generating = [False]  # Track if server is generating/sending audio
    is_client_playing = [False]  # Track if client is playing audio
    audio_end_sent = [False]  # Track if we've sent audio_end for current response
    transcript = []
    call_ended = threading.Event()
    end_reason = [None]  # Mutable container for end reason
    
    # Create call record in database
    call_id = None
    try:
        call_record = call_service.create_call(
            call_provider="websocket",
            agent_id=agent_id,  # Link call to specific agent
            user_id=user_id  # Link call to user who initiated
        )
        call_id = call_record.id
        print(f"📞 Browser call started with ID: {call_id}, Agent: {agent_config['agent_name']}, User: {user_id}")
    except Exception as e:
        print(f"⚠️ Could not create call record: {e}")
    
    # ==========================================================================
    # AGENT-FIRST: Generate opening message from the agent
    # The agent should always start the conversation as per the system prompt
    # ==========================================================================
    async def send_opening_message():
        """Generate and send the opening message from the agent based on system prompt.
        
        CONCURRENCY-SAFE: Uses agent-specific LLM and TTS (no globals).
        """
        nonlocal transcript
        
        opening_start = time.time()
        is_agent_generating[0] = True
        is_client_playing[0] = True
        audio_end_sent[0] = False
        
        try:
            # Use a special prompt to get just the opening line
            opening_prompt = "START_CONVERSATION"
            
            audio_queue = queue.Queue()
            processing_done = threading.Event()
            agent_response = []
            
            def process_opening():
                """Generate the opening message using agent-specific LLM."""
                try:
                    sentence_buffer = ""
                    sentence_end_pattern = re.compile(r'[.!?]\s*')
                    full_response = ""
                    tts_start = None
                    
                    # MULTI-TENANT: Use agent-specific LLM function
                    system_prompt = agent_config["system_prompt"]
                    if not system_prompt:
                        system_prompt = "You are a helpful AI voice assistant. Be concise and natural."
                    
                    for token in ask_ai_streaming_for_agent(
                        text=opening_prompt,
                        system_prompt=system_prompt,
                        history=agent_conversation_history,
                        kb_id=agent_config["kb_id"]
                    ):
                        sentence_buffer += token
                        full_response += token
                        
                        match = sentence_end_pattern.search(sentence_buffer)
                        if match:
                            end_pos = match.end()
                            sentence = sentence_buffer[:end_pos].strip()
                            sentence_buffer = sentence_buffer[end_pos:]
                            
                            if sentence:
                                sentence = clean_llm_output(sentence)
                                if sentence:
                                    if tts_start is None:
                                        tts_start = time.time()
                                    # MULTI-TENANT: Use agent-specific TTS voice
                                    for audio_chunk in text_to_speech_streaming_for_agent(
                                        sentence, agent_config["synthesis_voice"]
                                    ):
                                        audio_queue.put(audio_chunk)
                    
                    # Handle remaining text
                    remaining = sentence_buffer.strip()
                    if remaining:
                        remaining = clean_llm_output(remaining)
                        if remaining:
                            for audio_chunk in text_to_speech_streaming_for_agent(
                                remaining, agent_config["synthesis_voice"]
                            ):
                                audio_queue.put(audio_chunk)
                    
                    cleaned_response = clean_llm_output(full_response)
                    agent_response.append(cleaned_response)
                    
                except Exception as e:
                    print(f"❌ Opening error: {e}")
                finally:
                    processing_done.set()
            
            # Start processing thread
            threading.Thread(target=process_opening, daemon=True).start()
            
            # Send audio chunks to client
            chunk_count = 0
            first_chunk_sent = False
            while True:
                try:
                    audio_chunk = audio_queue.get(timeout=0.1)
                    await ws.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio_chunk).decode(),
                        "first_chunk": not first_chunk_sent
                    })
                    first_chunk_sent = True
                    chunk_count += 1
                except queue.Empty:
                    if processing_done.is_set():
                        break
                    continue
                except Exception as e:
                    print(f"   ❌ WebSocket error in opening: {e}")
                    break
            
            await ws.send_json({"type": "audio_end"})
            audio_end_sent[0] = True
            opening_time = (time.time() - opening_start) * 1000
            print(f"📞 OPENING: {opening_time:.0f}ms total")
            
            is_agent_generating[0] = False
            
            # Add to transcript and per-call conversation history
            if agent_response:
                transcript.append({
                    "role": "agent",
                    "text": agent_response[0],
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })
                agent_conversation_history.append({"role": "assistant", "content": agent_response[0]})
                
        except Exception as e:
            print(f"❌ Opening error: {e}")
            is_agent_generating[0] = False
            is_client_playing[0] = False
    
    # Silence monitoring task
    async def monitor_call_limits():
        """Monitor for silence timeout and max call duration"""
        nonlocal last_activity_time
        
        while not call_ended.is_set():
            await asyncio.sleep(1)
            
            current_time = time.time()
            call_duration = current_time - call_start_time
            
            # Check max call duration
            if call_duration >= settings.max_call_duration:
                end_reason[0] = "max_duration"
                call_ended.set()
                print(f"⏱️ Call ended: Maximum duration ({settings.max_call_duration}s) reached")
                break
            
            # Check silence timeout - ONLY after:
            # 1. Server finished sending audio (audio_end_sent)
            # 2. Client confirmed playback complete (last_playback_complete_time set)
            # 3. Not currently generating new response (is_agent_generating is False)
            if not is_agent_generating[0] and not is_client_playing[0] and last_playback_complete_time[0] is not None:
                silence_since_playback = current_time - last_playback_complete_time[0]
                
                # Debug log every 5 seconds
                if int(silence_since_playback) % 5 == 0 and int(silence_since_playback) > 0:
                    print(f"   ⏳ Silence: {int(silence_since_playback)}s / {settings.max_silence_duration}s")
                
                if silence_since_playback >= settings.max_silence_duration:
                    end_reason[0] = "silence_timeout"
                    call_ended.set()
                    print(f"🔇 Call ended: No response from user for {settings.max_silence_duration}s after playback finished")
                    break

    async def on_text(text: str, my_turn_id: int):
        """Handle recognized speech from user.
        
        CONCURRENCY-SAFE: Uses per-call turn tracking, conversation history,
        agent-specific LLM and TTS.
        """
        nonlocal last_activity_time
        
        print("🧑 STT:", repr(text))
        
        last_activity_time = time.time()
        
        if not text or not text.strip():
            return
        
        # Add user message to transcript
        transcript.append({
            "role": "user",
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        
        # MULTI-TENANT: Use per-call conversation history (not global)
        agent_conversation_history.append({"role": "user", "content": text})
        
        # Check for end intent (simple keyword check first)
        if detect_end_intent_simple(text):
            print("👋 End intent detected (keyword match)")
            
            # Say goodbye
            goodbye_msg = "Thank you for calling. Goodbye!"
            transcript.append({
                "role": "agent",
                "text": goodbye_msg,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            })
            
            # Send goodbye audio
            try:
                for audio_chunk in text_to_speech_streaming_for_agent(
                    goodbye_msg, agent_config["synthesis_voice"]
                ):
                    await ws.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio_chunk).decode()
                    })
                await ws.send_json({"type": "audio_end"})
            except Exception as e:
                print(f"   ⚠️ Error sending goodbye: {e}")
            
            end_reason[0] = "user_intent"
            call_ended.set()
            return

        try:
            print("🔄 Starting processing...")
            
            # Mark that agent is generating (barge-in should be enabled)
            is_agent_generating[0] = True
            is_client_playing[0] = True  # Will be playing soon
            audio_end_sent[0] = False
            last_playback_complete_time[0] = None  # Reset until client finishes playback
            
            audio_queue = queue.Queue()
            processing_done = threading.Event()
            agent_response = []  # Collect full response for transcript
            
            # Timing metrics
            processing_start_time = time.time()
            first_token_time = [None]
            first_audio_time = [None]
            llm_end_time = [None]
            
            def process_pipeline():
                """Background thread: LLM → sentence detection → TTS → audio queue
                
                CONCURRENCY-SAFE: Uses agent-specific LLM and TTS (no globals).
                Uses per-call turn tracking for barge-in.
                
                OPTIMIZATIONS v2:
                1. Aggressive early flush: trigger on comma/semicolon after just 5 words
                2. Split long sentences (>15 words) at natural break points
                3. Concurrent TTS preparation for upcoming sentences
                """
                try:
                    sentence_buffer = ""
                    # OPTIMIZED: Detect sentences on .!? 
                    sentence_end_pattern = re.compile(r'[.!?]\s*')
                    # Secondary pattern for early flush on commas (faster first audio)
                    early_flush_pattern = re.compile(r'[,;:]\s+')
                    # Pattern to split very long sentences at natural break points
                    long_sentence_break = re.compile(r'\s+(and|or|but|so|because|which|that|where|when)\s+', re.IGNORECASE)
                    full_llm_response = ""
                    token_count = [0]
                    words_since_flush = [0]

                    print(f"   🤖 LLM streaming for agent: {agent_config['agent_name']}...")
                    llm_start = time.time()
                    
                    # MULTI-TENANT: Use agent-specific LLM function
                    system_prompt = agent_config["system_prompt"]
                    if not system_prompt:
                        system_prompt = "You are a helpful AI voice assistant. Be concise and natural."
                    
                    for token in ask_ai_streaming_for_agent(
                        text=text,
                        system_prompt=system_prompt,
                        history=agent_conversation_history,
                        kb_id=agent_config["kb_id"]
                    ):
                        if my_turn_id != call_turn_id[0]:
                            print("⚡ BARGE-IN: LLM stopped")
                            return
                        
                        token_count[0] += 1
                        if first_token_time[0] is None:
                            first_token_time[0] = time.time()
                            ttft = (first_token_time[0] - processing_start_time) * 1000
                            print(f"   ⚡ TTFT: {ttft:.0f}ms")

                        sentence_buffer += token
                        full_llm_response += token
                        words_since_flush[0] = len(sentence_buffer.split())
                        
                        # Check for sentence end (.!?)
                        match = sentence_end_pattern.search(sentence_buffer)
                        
                        # OPTIMIZATION v2: Early flush on comma/colon if we have 5+ words (reduced from 8)
                        # This gets first audio out ~200ms faster
                        if not match and words_since_flush[0] >= 5 and first_audio_time[0] is None:
                            early_match = early_flush_pattern.search(sentence_buffer)
                            if early_match:
                                match = early_match  # Use the early match point
                        
                        # OPTIMIZATION v2: Also flush long buffers (15+ words) at conjunction breaks
                        # This prevents very long TTS calls which are slow
                        if not match and words_since_flush[0] >= 15:
                            long_match = long_sentence_break.search(sentence_buffer)
                            if long_match:
                                # Split before the conjunction
                                match = long_match
                        
                        if match:
                            end_pos = match.end()
                            sentence = sentence_buffer[:end_pos].strip()
                            sentence_buffer = sentence_buffer[end_pos:]
                            words_since_flush[0] = 0
                            
                            if sentence:
                                sentence = clean_llm_output(sentence)
                                if not sentence:
                                    continue
                                
                                # MULTI-TENANT: Use agent-specific TTS voice
                                for audio_chunk in text_to_speech_streaming_for_agent(
                                    sentence, agent_config["synthesis_voice"]
                                ):
                                    if my_turn_id != call_turn_id[0]:
                                        print("⚡ BARGE-IN: TTS stopped")
                                        return
                                    
                                    if first_audio_time[0] is None:
                                        first_audio_time[0] = time.time()
                                        latency = (first_audio_time[0] - processing_start_time) * 1000
                                        print(f"   🔊 First audio: {latency:.0f}ms")
                                    
                                    audio_queue.put(audio_chunk)

                    remaining = sentence_buffer.strip()
                    if remaining:
                        remaining = clean_llm_output(remaining)
                        if remaining:
                            for audio_chunk in text_to_speech_streaming_for_agent(
                                remaining, agent_config["synthesis_voice"]
                            ):
                                if my_turn_id != call_turn_id[0]:
                                    return
                                if first_audio_time[0] is None:
                                    first_audio_time[0] = time.time()
                                    latency = (first_audio_time[0] - processing_start_time) * 1000
                                    print(f"   🔊 First audio: {latency:.0f}ms")
                                audio_queue.put(audio_chunk)
                    
                    llm_end_time[0] = time.time()
                    llm_total = (llm_end_time[0] - llm_start) * 1000
                    total_latency = (llm_end_time[0] - processing_start_time) * 1000
                    
                    cleaned_response = clean_llm_output(full_llm_response)
                    agent_response.append(cleaned_response)
                    print(f"   📊 TIMING: LLM={llm_total:.0f}ms | Tokens={token_count[0]} | Total={total_latency:.0f}ms")

                except Exception as e:
                    print(f"   ❌ Pipeline error: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    processing_done.set()
            
            # Start processing thread
            threading.Thread(target=process_pipeline, daemon=True).start()
            
            chunk_count = 0
            first_chunk_sent = False
            while True:
                if my_turn_id != call_turn_id[0]:
                    print("⚡ BARGE-IN: Stopping transmission")
                    try:
                        await ws.send_json({"type": "barge_in"})
                    except:
                        pass
                    break

                try:
                    audio_chunk = audio_queue.get(timeout=0.1)
                    await ws.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio_chunk).decode(),
                        "first_chunk": not first_chunk_sent
                    })
                    first_chunk_sent = True
                    chunk_count += 1
                except queue.Empty:
                    if processing_done.is_set():
                        break
                    continue
                except Exception as e:
                    print(f"   ❌ WebSocket error: {e}")
                    break
            
            if my_turn_id == call_turn_id[0]:
                await ws.send_json({"type": "audio_end"})
                audio_end_sent[0] = True
                
                is_agent_generating[0] = False
                
                # Add agent response to transcript
                if agent_response:
                    transcript.append({
                        "role": "agent",
                        "text": agent_response[0],
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
                    
                    # MULTI-TENANT: Use per-call conversation history
                    agent_conversation_history.append({"role": "assistant", "content": agent_response[0]})
                    
                    # Check if LLM response indicates end of conversation
                    if detect_end_intent_simple(agent_response[0]):
                        end_reason[0] = "conversation_complete"
            else:
                # Barge-in happened - reset all flags
                is_agent_generating[0] = False
                is_client_playing[0] = False
            
        except Exception as e:
            print(f"❌ Error in on_text: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            # Ensure flags are reset on error
            is_agent_generating[0] = False
            is_client_playing[0] = False

    def on_text_callback(text: str):
        """CONCURRENCY-SAFE: Uses per-call turn tracking."""
        with call_turn_lock:
            call_turn_id[0] += 1
            my_turn_id = call_turn_id[0]
        
        asyncio.run_coroutine_threadsafe(on_text(text, my_turn_id), loop)

    def on_barge_in_callback():
        """Called when STT detects partial speech - immediately interrupt TTS.
        CONCURRENCY-SAFE: Uses per-call turn tracking.
        """
        if is_agent_generating[0] or is_client_playing[0]:
            with call_turn_lock:
                call_turn_id[0] += 1
            
            is_client_playing[0] = False
            print("⚡ BARGE-IN detected")
            
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "barge_in"}),
                    loop
                )
            except Exception:
                pass

    # MULTI-TENANT: Use agent-specific STT recognizer
    recognizer, audio_stream = create_streaming_recognizer_for_agent(
        recognition_language=agent_config["recognition_language"],
        on_text_callback=on_text_callback,
        on_barge_in_callback=on_barge_in_callback,
        sample_rate=16000
    )
    
    # Start call limit monitor
    monitor_task = asyncio.create_task(monitor_call_limits())
    
    # AGENT-FIRST: Send opening message from agent before listening for user input
    await send_opening_message()

    try:
        while not call_ended.is_set():
            try:
                # Use timeout to periodically check call_ended flag
                msg = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                
                if msg["type"] == "audio":
                    pcm = base64.b64decode(msg["data"])
                    audio_stream.write(pcm)
                
                elif msg["type"] == "playback_complete":
                    # Client finished playing all audio
                    is_client_playing[0] = False
                    
                    # Check if call should end after this playback (agent said goodbye)
                    if end_reason[0] == "conversation_complete":
                        print(f"   🔈 Playback complete - ending call now")
                        call_ended.set()
                    # Only start silence timer if server also finished sending audio
                    # (Don't start timer if new audio is being generated)
                    elif audio_end_sent[0] and not is_agent_generating[0]:
                        last_playback_complete_time[0] = time.time()
                        print(f"   🔈 Client playback complete - silence timer started ({settings.max_silence_duration}s)")
                    
            except asyncio.TimeoutError:
                # Normal timeout, just check the loop condition
                continue
            except Exception as e:
                print(f"❌ WebSocket error: {e}")
                break
        
        # Call ended - send end signal to client
        if end_reason[0]:
            try:
                await ws.send_json({
                    "type": "call_end",
                    "reason": end_reason[0]
                })
            except:
                pass

    except Exception as e:
        print("❌ WebSocket closed:", e)
        end_reason[0] = "connection_closed"

    finally:
        # Cleanup
        monitor_task.cancel()
        recognizer.stop_continuous_recognition()
        audio_stream.close()
        
        # Calculate call duration
        call_duration = time.time() - call_start_time
        
        # Save transcript to file and database
        if transcript:
            save_transcript(transcript, call_duration, call_id=call_id, end_reason=end_reason[0])
        elif call_id:
            # No transcript but we have a call record - still update end info
            try:
                call_service.end_call(call_id, end_reason=end_reason[0] or "no_transcript", duration_seconds=int(call_duration))
            except:
                pass
        
        print(f"📞 Call ended. Duration: {call_duration:.1f}s, Reason: {end_reason[0]}")


# ============================================================================
# FreJun (Teler) WebSocket Handler for Phone Calls
# ============================================================================

@app.websocket("/ws/frejun-audio")
async def frejun_audio_ws(ws: WebSocket):
    """
    WebSocket handler for FreJun media streaming.
    
    MULTI-TENANT: Accepts agent_id query parameter to load agent-specific config.
    
    FreJun sends:
    - {"type": "start", ...} - Stream metadata
    - {"type": "audio", "data": {"audio_b64": "..."}} - Audio chunks
    
    We send back:
    - {"type": "audio", "audio_b64": "...", "chunk_id": N} - Response audio
    - {"type": "clear"} - Clear audio buffer (for barge-in)
    """
    global current_turn_id
    
    # Log connection details for debugging
    print(f"🔗 FreJun WebSocket connection attempt from: {ws.client}")
    print(f"   Headers: {dict(ws.headers)}")
    
    # =========================================================================
    # MULTI-TENANT: Parse agent_id from query string and load configuration
    # =========================================================================
    agent_id = ws.query_params.get("agent_id")
    query_call_id = ws.query_params.get("call_id")
    query_campaign_id = ws.query_params.get("campaign_id")
    query_user_id = ws.query_params.get("user_id")
    
    # Agent-specific configuration (defaults to global settings)
    agent_config = {
        "system_prompt": None,  # Will use default if None
        "kb_id": None,  # Knowledge base ID
        "recognition_language": "en-IN",
        "synthesis_voice": "en-IN-NeerjaNeural",
        "agent_name": "Default Agent",
        "max_call_duration": 10 * 60,  # 10 minutes
        "max_silence_duration": 20,  # 20 seconds
    }
    
    # If no agent_id in query params, try to find it from active_calls
    # (the flow endpoint stores agent_id/user_id from the initiate-call request)
    if not agent_id:
        from app.api.frejun import active_calls as frejun_active_calls
        # Find the most recent active call that has an agent_id
        for cid, cinfo in frejun_active_calls.items():
            if cinfo.get("agent_id") and cinfo.get("status") in ("initiated", "connected"):
                agent_id = cinfo["agent_id"]
                if not query_user_id:
                    query_user_id = cinfo.get("user_id")
                if not query_campaign_id:
                    query_campaign_id = cinfo.get("campaign_id")
                print(f"   🔍 Found agent_id from active_calls: {agent_id}")
                break
    
    if agent_id:
        try:
            from app.db.service import agent_service
            agent = agent_service.get_agent(agent_id)
            if agent:
                print(f"   🤖 Loading agent: {agent.name} (ID: {agent_id})")
                agent_config["agent_name"] = agent.name
                # Use get_resolved_system_prompt() for variable substitution (same as browser WS)
                agent_config["system_prompt"] = agent.get_resolved_system_prompt()
                agent_config["kb_id"] = agent.active_kb_id
                agent_config["recognition_language"] = agent.recognition_language or "en-IN"
                agent_config["synthesis_voice"] = agent.synthesis_voice_name or "en-IN-NeerjaNeural"
                agent_config["max_call_duration"] = agent.max_call_duration or 600
                agent_config["max_silence_duration"] = agent.max_silence_duration or 20
                print(f"   📚 KB: {agent_config['kb_id']}, Voice: {agent_config['synthesis_voice']}")
                
                # Apply campaign-specific CSV variables to the system prompt
                # (override agent's default prompt_variables with per-call values)
                from app.api.frejun import active_calls as frejun_active_calls
                campaign_variables = None
                for cid, cinfo in frejun_active_calls.items():
                    if cinfo.get("agent_id") == agent_id and cinfo.get("campaign_id"):
                        campaign_variables = cinfo.get("variables", {})
                        break
                
                if campaign_variables:
                    prompt = agent_config["system_prompt"]
                    for key, value in campaign_variables.items():
                        if value:
                            prompt = prompt.replace(f"{{{key}}}", str(value))
                    agent_config["system_prompt"] = prompt
                    print(f"   📝 Applied campaign variables: {list(campaign_variables.keys())}")
            else:
                print(f"   ⚠️ Agent {agent_id} not found in DB, using defaults")
        except Exception as e:
            print(f"   ⚠️ Error loading agent config: {e}")
    else:
        print(f"   ⚠️ No agent_id provided and none found in active_calls, using defaults")
    
    # Agent-specific conversation history (not global!)
    agent_conversation_history = []
    
    try:
        # Accept the WebSocket connection
        await ws.accept()
        print("🔗 FreJun WebSocket connected successfully")
    except Exception as e:
        print(f"❌ WebSocket connection failed: {e}")
        return
    
    loop = asyncio.get_running_loop()
    
    # Call state
    call_start_time = time.time()
    stream_id = None
    sample_rate = 8000  # Default, may be updated from 'start' message
    transcript = []
    call_ended = threading.Event()
    end_reason = [None]
    is_agent_generating = [False]
    audio_chunk_id = [0]
    last_audio_sent_time = [0]  # Track when we last sent audio (for barge-in timing)
    phone_numbers = {"from": None, "to": None}  # Will be set from stream start message
    
    # Import active_calls from frejun API
    from app.api.frejun import active_calls
    
    # Try to find the existing call record created by initiate_call()
    # instead of creating a duplicate record
    call_id = None
    try:
        # Look through active_calls to find the matching call's provider_call_id
        matched_provider_call_id = None
        for cid, cinfo in active_calls.items():
            if cinfo.get("agent_id") == agent_id and cinfo.get("status") in ("initiated", "connected"):
                matched_provider_call_id = cinfo.get("frejun_call_id", cid)
                break
        
        if matched_provider_call_id:
            # Look up existing call record by provider_call_id
            existing_call = call_service.get_call_by_provider_id(matched_provider_call_id)
            if existing_call:
                call_id = existing_call.id
                print(f"📞 FreJun WS linked to existing call: {call_id} (provider: {matched_provider_call_id}), Agent: {agent_config['agent_name']}")
        
        # If no existing record found (e.g., incoming call), create a new one
        if not call_id:
            call_record = call_service.create_call(
                call_provider="frejun",
                agent_id=agent_id
            )
            call_id = call_record.id
            print(f"📞 FreJun call started with new ID: {call_id}, Agent: {agent_config['agent_name']}")
    except Exception as e:
        print(f"⚠️ Could not find/create call record: {e}")
    
    async def send_audio_to_frejun(audio_data: bytes):
        """Send audio chunk to FreJun for playback"""
        nonlocal audio_chunk_id, last_audio_sent_time
        audio_chunk_id[0] += 1
        last_audio_sent_time[0] = time.time()  # Track when we sent audio
        
        # FreJun expects base64 encoded audio
        audio_b64 = base64.b64encode(audio_data).decode()
        
        await ws.send_json({
            "type": "audio",
            "audio_b64": audio_b64,
            "chunk_id": audio_chunk_id[0]
        })
    
    async def send_clear_to_frejun():
        """Clear FreJun's audio buffer (for barge-in)
        
        According to FreJun docs:
        - {"type": "clear"} - Wipes out entire buffer of queued chunks
        - {"type": "interrupt", "chunk_id": N} - Interrupts a specific chunk
        """
        print(f"   🛑 Sending CLEAR command to FreJun (last chunk: {audio_chunk_id[0]})")
        
        # First, send interrupt for recent chunks (in case they're playing)
        current_chunk = audio_chunk_id[0]
        for i in range(max(1, current_chunk - 5), current_chunk + 1):
            try:
                await ws.send_json({"type": "interrupt", "chunk_id": i})
            except:
                pass
        
        # Then send clear to wipe any queued chunks
        await ws.send_json({"type": "clear"})
    
    async def on_text(text: str, my_turn_id: int):
        """Handle recognized speech from user"""
        global current_turn_id
        
        print("🧑 STT:", repr(text))
        
        if not text or not text.strip():
            return
        
        transcript.append({
            "role": "user",
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        # MULTI-TENANT: Use per-call history instead of global
        agent_conversation_history.append({"role": "user", "content": text})
        
        # Check for end intent
        if detect_end_intent_simple(text):
            goodbye_msg = "Thank you for calling. Goodbye!"
            transcript.append({
                "role": "agent",
                "text": goodbye_msg,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            })
            
            # MULTI-TENANT: Use agent-specific voice
            for audio_chunk in text_to_speech_telephony_for_agent(goodbye_msg, agent_config["synthesis_voice"]):
                await send_audio_to_frejun(audio_chunk)
            
            end_reason[0] = "user_intent"
            call_ended.set()
            return
        
        try:
            is_agent_generating[0] = True
            
            audio_queue = queue.Queue()
            processing_done = threading.Event()
            agent_response = []
            
            processing_start_time = time.time()
            
            def process_pipeline():
                try:
                    sentence_buffer = ""
                    sentence_end_pattern = re.compile(r'[.!?]\s*')
                    full_llm_response = ""
                    
                    print(f"   🤖 LLM streaming for agent: {agent_config['agent_name']}...")
                    
                    # MULTI-TENANT: Use agent-specific LLM function (never fall back to agent_config.json)
                    from app.services.llm import ask_ai_streaming_for_agent
                    
                    # Get system prompt (agent-specific or generic default)
                    system_prompt = agent_config["system_prompt"]
                    if not system_prompt:
                        system_prompt = "You are a helpful AI voice assistant. Be concise and natural."
                    
                    for token in ask_ai_streaming_for_agent(
                        text=text,
                        system_prompt=system_prompt,
                        history=agent_conversation_history,
                        kb_id=agent_config["kb_id"]
                    ):
                        if my_turn_id != current_turn_id:
                            print("⚡ BARGE-IN: LLM stopped")
                            return
                        
                        sentence_buffer += token
                        full_llm_response += token
                        
                        match = sentence_end_pattern.search(sentence_buffer)
                        if match:
                            end_pos = match.end()
                            sentence = sentence_buffer[:end_pos].strip()
                            sentence_buffer = sentence_buffer[end_pos:]
                            
                            if sentence:
                                sentence = clean_llm_output(sentence)
                                if sentence:
                                    for audio_chunk in text_to_speech_telephony_for_agent(sentence, agent_config["synthesis_voice"]):
                                        if my_turn_id != current_turn_id:
                                            return
                                        audio_queue.put(audio_chunk)
                    
                    remaining = sentence_buffer.strip()
                    if remaining:
                        remaining = clean_llm_output(remaining)
                        if remaining:
                            for audio_chunk in text_to_speech_telephony_for_agent(remaining, agent_config["synthesis_voice"]):
                                if my_turn_id != current_turn_id:
                                    return
                                audio_queue.put(audio_chunk)
                    
                    cleaned_response = clean_llm_output(full_llm_response)
                    agent_response.append(cleaned_response)
                    
                    total_time = (time.time() - processing_start_time) * 1000
                    print(f"   📊 TIMING: Total={total_time:.0f}ms")
                    
                except Exception as e:
                    print(f"   ❌ Pipeline error: {e}")
                finally:
                    processing_done.set()
            
            threading.Thread(target=process_pipeline, daemon=True).start()
            
            # Send audio to FreJun as it becomes available
            while True:
                if my_turn_id != current_turn_id:
                    print("⚡ BARGE-IN: Stopping transmission")
                    await send_clear_to_frejun()
                    break
                
                try:
                    audio_chunk = audio_queue.get(timeout=0.1)
                    await send_audio_to_frejun(audio_chunk)
                except queue.Empty:
                    if processing_done.is_set():
                        break
                    continue
            
            is_agent_generating[0] = False
            
            if agent_response:
                transcript.append({
                    "role": "agent",
                    "text": agent_response[0],
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                })
                # MULTI-TENANT: Use per-call history
                agent_conversation_history.append({"role": "assistant", "content": agent_response[0]})
                
                if detect_end_intent_simple(agent_response[0]):
                    end_reason[0] = "conversation_complete"
                    call_ended.set()
                    
        except Exception as e:
            print(f"❌ Error in FreJun on_text: {e}")
            is_agent_generating[0] = False
    
    def on_text_callback(text: str):
        global current_turn_id
        
        with current_turn_lock:
            current_turn_id += 1
            my_turn_id = current_turn_id
        
        asyncio.run_coroutine_threadsafe(on_text(text, my_turn_id), loop)
    
    def on_barge_in_callback():
        """
        Called when the user starts speaking during agent response.
        Immediately stops LLM generation and clears FreJun audio buffer.
        
        IMPORTANT: We always send a clear command because:
        - The server might have finished sending audio, but it's still playing on the phone
        - There's network/buffer delay between sending and hearing
        - FreJun may have buffered audio that needs to be cleared
        """
        global current_turn_id
        
        # Calculate time since last audio was sent (if tracked)
        time_since_last_audio = time.time() - last_audio_sent_time[0] if last_audio_sent_time[0] else float('inf')
        
        # Barge-in is relevant if:
        # 1. We're currently generating, OR
        # 2. Audio was sent recently (within last 5 seconds - buffer/playback time)
        should_barge_in = is_agent_generating[0] or time_since_last_audio < 5.0
        
        if should_barge_in:
            with current_turn_lock:
                current_turn_id += 1
                new_turn = current_turn_id
            
            print(f"⚡ BARGE-IN detected! Stopping agent (turn {new_turn})")
            print(f"   is_generating={is_agent_generating[0]}, time_since_audio={time_since_last_audio:.1f}s")
            is_agent_generating[0] = False  # Mark as not generating immediately
            
            # Send clear command to FreJun to stop audio playback
            try:
                asyncio.run_coroutine_threadsafe(
                    send_clear_to_frejun(),
                    loop
                )
            except Exception as e:
                print(f"   ⚠️ Error sending clear: {e}")
    
    # Create STT recognizer - will be initialized after we know sample rate
    recognizer = None
    audio_stream = None
    opening_sent = [False]
    
    try:
        # Wait for messages from FreJun
        while not call_ended.is_set():
            try:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=30.0)
                msg_type = msg.get("type", "")
                
                if msg_type == "start":
                    # Stream started - initialize STT with correct sample rate
                    data = msg.get("data", {})
                    sample_rate = data.get("sample_rate", 8000)
                    stream_id = msg.get("stream_id")
                    frejun_call_id = data.get("call_id") or msg.get("call_id")
                    print(f"📡 FreJun stream started: {stream_id}, sample_rate={sample_rate}")
                    print(f"   FreJun Call ID: {frejun_call_id}")
                    
                    # If we don't have a linked call record yet, try to find it
                    # now that we have the actual frejun_call_id from the stream
                    if frejun_call_id and call_id:
                        existing = call_service.get_call_by_provider_id(frejun_call_id)
                        if existing and existing.id != call_id:
                            # We created a duplicate earlier - use the original and 
                            # clean up the duplicate if it has no data
                            old_call_id = call_id
                            call_id = existing.id
                            print(f"   🔗 Re-linked to original call record: {call_id} (was: {old_call_id})")
                            # Delete the orphan record we created
                            try:
                                from app.db.session import SessionLocal
                                from app.db.models import Call
                                db = SessionLocal()
                                orphan = db.query(Call).filter(Call.id == old_call_id).first()
                                if orphan and not orphan.end_time and not orphan.provider_call_id:
                                    db.delete(orphan)
                                    db.commit()
                                    print(f"   🧹 Cleaned up orphan call record: {old_call_id}")
                                db.close()
                            except Exception:
                                pass
                    
                    # Try to get phone numbers from the stream data or active_calls
                    from_num = data.get("from") or data.get("from_number")
                    to_num = data.get("to") or data.get("to_number")
                    
                    # If not in stream data, check active_calls using any identifier we have
                    if not (from_num and to_num):
                        for cid, cinfo in active_calls.items():
                            if cinfo.get("frejun_call_id") == frejun_call_id or cid == frejun_call_id:
                                from_num = from_num or cinfo.get("from_number")
                                to_num = to_num or cinfo.get("to_number")
                                print(f"   Found phone numbers from active_calls: {from_num} -> {to_num}")
                                break
                    
                    # Always update provider_call_id to the real FreJun call ID
                    # so webhooks (call.completed, recording.completed) can find this record
                    if call_id and frejun_call_id:
                        try:
                            call_service.update_call_phone_numbers(
                                call_id,
                                from_number=from_num,
                                to_number=to_num,
                                provider_call_id=frejun_call_id
                            )
                            print(f"   🔗 Updated provider_call_id to: {frejun_call_id}")
                        except Exception as e:
                            print(f"   ⚠️ Could not update call record: {e}")
                    
                    # Create recognizer for this call (use agent-specific language)
                    from app.services.speech import create_streaming_recognizer_for_agent
                    recognizer, audio_stream = create_streaming_recognizer_for_agent(
                        recognition_language=agent_config["recognition_language"],
                        on_text_callback=on_text_callback, 
                        on_barge_in_callback=on_barge_in_callback,
                        sample_rate=sample_rate
                    )
                    
                    # NOW send opening message after stream is established
                    if not opening_sent[0]:
                        opening_sent[0] = True
                        print("🎤 Sending FreJun opening message...")
                        opening_start = time.time()
                        
                        opening_prompt = "START_CONVERSATION"
                        
                        # MULTI-TENANT: Use agent-specific LLM and TTS (never fall back to agent_config.json)
                        from app.services.llm import ask_ai_streaming_for_agent
                        system_prompt = agent_config["system_prompt"]
                        if not system_prompt:
                            system_prompt = "You are a helpful AI voice assistant. Be concise and natural."
                        
                        opening_text = "".join([t for t in ask_ai_streaming_for_agent(
                            text=opening_prompt,
                            system_prompt=system_prompt,
                            history=agent_conversation_history,
                            kb_id=agent_config["kb_id"]
                        )])
                        cleaned_opening = clean_llm_output(opening_text)
                        
                        if cleaned_opening:
                            for sentence_audio in text_to_speech_telephony_for_agent(
                                cleaned_opening, agent_config["synthesis_voice"]
                            ):
                                await send_audio_to_frejun(sentence_audio)
                            # Add opening to conversation history
                            agent_conversation_history.append({"role": "assistant", "content": cleaned_opening})
                            transcript.append({
                                "role": "agent",
                                "text": cleaned_opening,
                                "timestamp": datetime.now().strftime("%H:%M:%S")
                            })
                        
                        opening_time = (time.time() - opening_start) * 1000
                        print(f"📞 Opening sent: {opening_time:.0f}ms")
                    
                elif msg_type == "audio":
                    # Audio chunk from FreJun (caller's voice)
                    data = msg.get("data", {})
                    audio_b64 = data.get("audio_b64", "")
                    
                    if audio_b64 and audio_stream:
                        audio_bytes = base64.b64decode(audio_b64)
                        audio_stream.write(audio_bytes)
                        
            except asyncio.TimeoutError:
                # No message for 30 seconds - end call
                print("⏰ FreJun call timeout - no activity")
                end_reason[0] = "timeout"
                break
            except Exception as e:
                print(f"❌ FreJun WebSocket error: {e}")
                break
                
    except Exception as e:
        print(f"❌ FreJun connection error: {e}")
        end_reason[0] = "connection_error"
        
    finally:
        # Cleanup
        if recognizer:
            try:
                recognizer.stop_continuous_recognition()
            except:
                pass
        if audio_stream:
            try:
                audio_stream.close()
            except:
                pass
        
        call_duration = time.time() - call_start_time
        
        if transcript:
            save_transcript(transcript, call_duration, call_id=call_id, end_reason=end_reason[0])
        elif call_id:
            try:
                call_service.end_call(call_id, end_reason=end_reason[0] or "no_transcript", duration_seconds=int(call_duration))
            except:
                pass
        
        print(f"📞 FreJun call ended. Duration: {call_duration:.1f}s, Reason: {end_reason[0]}")

