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

# Global turn tracking for barge-in support
current_turn_id = 0
current_turn_lock = threading.Lock()

from app.services.llm import ask_ai, ask_ai_streaming, reset_conversation, add_to_conversation, clean_llm_output
from app.services.speech import (
    text_to_speech,
    text_to_speech_streaming,
    create_streaming_recognizer,
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

app = FastAPI(title="Anvenssa Voice Agent API")

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
                    "start_time": c.start_time.isoformat() if c.start_time else None,
                    "end_time": c.end_time.isoformat() if c.end_time else None,
                    "duration": c.duration_seconds,
                    "end_reason": c.end_reason
                }
                for c in calls
            ]
        }
    except Exception as e:
        return {"error": str(e), "calls": []}


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
            "start_time": call.start_time.isoformat() if call.start_time else None,
            "end_time": call.end_time.isoformat() if call.end_time else None,
            "duration": call.duration_seconds,
            "end_reason": call.end_reason,
            "transcript": transcript_content
        }
    except Exception as e:
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
    try:
        # Generate unique ID
        kb_id = str(uuid.uuid4())[:8]
        
        # Read file content
        content = await file.read()
        filename = file.filename or "uploaded_file"
        
        # Save the original file
        file_path = get_kb_file_path(kb_id, filename)
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Extract text based on file type
        text_content = ""
        if filename.lower().endswith('.pdf'):
            try:
                import fitz  # PyMuPDF
                pdf_doc = fitz.open(stream=content, filetype="pdf")
                for page in pdf_doc:
                    text_content += page.get_text()
                pdf_doc.close()
            except ImportError:
                # Fallback: try with pdfplumber
                try:
                    import pdfplumber
                    import io
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        for page in pdf.pages:
                            text_content += page.extract_text() or ""
                except ImportError:
                    return {"error": "PDF processing library not installed. Install pymupdf or pdfplumber."}
        elif filename.lower().endswith('.txt') or filename.lower().endswith('.md'):
            text_content = content.decode('utf-8', errors='ignore')
        else:
            return {"error": f"Unsupported file type: {filename}. Supported: .pdf, .txt, .md"}
        
        if not text_content.strip():
            return {"error": "Could not extract text from file"}
        
        # Create knowledge base in vector store
        chunk_count = create_knowledge_base_from_text(kb_id, name, text_content)
        
        # Save to config
        kb = agent_config_service.add_knowledge_base(
            kb_id=kb_id,
            name=name,
            filename=filename,
            chunk_count=chunk_count
        )
        
        print(f"📚 Created knowledge base: {name} ({kb_id}) with {chunk_count} chunks")
        
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
        traceback.print_exc()
        return {"error": str(e)}


@app.post("/api/agent/knowledge-bases/{kb_id}/activate")
def activate_knowledge_base(kb_id: str):
    """Set a knowledge base as active"""
    success = agent_config_service.set_active_knowledge_base(kb_id)
    
    if success:
        # Update vector store to use this KB
        set_active_knowledge_base(kb_id)
        print(f"📚 Activated knowledge base: {kb_id}")
        return {"success": True, "active_id": kb_id}
    else:
        return {"error": "Knowledge base not found"}


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
    voices = [
        # English - India (Most Natural)
        {"id": "en-IN-NeerjaNeural", "name": "Neerja (Indian English, Female) ⭐ Recommended", "language": "en-IN"},
        {"id": "en-IN-PrabhatNeural", "name": "Prabhat (Indian English, Male)", "language": "en-IN"},
        # English - US (Very Natural)
        {"id": "en-US-JennyNeural", "name": "Jenny (US English, Female) ⭐ Very Natural", "language": "en-US"},
        {"id": "en-US-JennyMultilingualNeural", "name": "Jenny Multilingual (US, Female) ⭐ Most Natural", "language": "en-US"},
        {"id": "en-US-GuyNeural", "name": "Guy (US English, Male)", "language": "en-US"},
        {"id": "en-US-AriaNeural", "name": "Aria (US English, Female) ⭐ Conversational", "language": "en-US"},
        {"id": "en-US-DavisNeural", "name": "Davis (US English, Male) ⭐ Warm", "language": "en-US"},
        {"id": "en-US-JasonNeural", "name": "Jason (US English, Male)", "language": "en-US"},
        {"id": "en-US-SaraNeural", "name": "Sara (US English, Female)", "language": "en-US"},
        # English - UK
        {"id": "en-GB-SoniaNeural", "name": "Sonia (British English, Female)", "language": "en-GB"},
        {"id": "en-GB-RyanNeural", "name": "Ryan (British English, Male)", "language": "en-GB"},
        # Hindi
        {"id": "hi-IN-SwaraNeural", "name": "Swara (Hindi, Female)", "language": "hi-IN"},
        {"id": "hi-IN-MadhurNeural", "name": "Madhur (Hindi, Male)", "language": "hi-IN"},
        # Spanish
        {"id": "es-ES-ElviraNeural", "name": "Elvira (Spanish, Female)", "language": "es-ES"},
        {"id": "es-MX-DaliaNeural", "name": "Dalia (Mexican Spanish, Female)", "language": "es-MX"},
        # French
        {"id": "fr-FR-DeniseNeural", "name": "Denise (French, Female)", "language": "fr-FR"},
        # German
        {"id": "de-DE-KatjaNeural", "name": "Katja (German, Female)", "language": "de-DE"},
        # Japanese
        {"id": "ja-JP-NanamiNeural", "name": "Nanami (Japanese, Female)", "language": "ja-JP"},
        # Chinese
        {"id": "zh-CN-XiaoxiaoNeural", "name": "Xiaoxiao (Chinese, Female)", "language": "zh-CN"},
    ]
    
    languages = [
        {"id": "en-IN", "name": "English (India)"},
        {"id": "en-US", "name": "English (US)"},
        {"id": "en-GB", "name": "English (UK)"},
        {"id": "hi-IN", "name": "Hindi (India)"},
        {"id": "es-ES", "name": "Spanish (Spain)"},
        {"id": "es-MX", "name": "Spanish (Mexico)"},
        {"id": "fr-FR", "name": "French (France)"},
        {"id": "de-DE", "name": "German (Germany)"},
        {"id": "ja-JP", "name": "Japanese (Japan)"},
        {"id": "zh-CN", "name": "Chinese (Mainland)"},
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


def save_transcript(transcript: list, call_duration: float, call_id: str = None, end_reason: str = None):
    """Save call transcript to database only"""
    
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
        except Exception as e:
            print(f"⚠️ Could not save to database: {e}")
    else:
        print("⚠️ No call_id provided, transcript not saved")
    
    return call_id


@app.get("/")
def health():
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket):
    global current_turn_id
    
    await ws.accept()
    print("🔗 WebSocket connected")

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
        call_record = call_service.create_call(call_provider="websocket")
        call_id = call_record.id
        print(f"📞 Call started with ID: {call_id}")
        
        # Reset conversation history for this new call
        reset_conversation()
    except Exception as e:
        print(f"⚠️ Could not create call record: {e}")
    
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
        global current_turn_id
        nonlocal last_activity_time
        
        print("🧑 STT:", repr(text))
        
        # Update activity time
        last_activity_time = time.time()
        
        # Skip empty or whitespace-only text
        if not text or not text.strip():
            print("⚠️ Empty STT result, skipping...")
            return
        
        # Add user message to transcript
        transcript.append({
            "role": "user",
            "text": text,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        
        # Add to conversation history for LLM context
        add_to_conversation("user", text)
        
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
                for audio_chunk in text_to_speech_streaming(goodbye_msg):
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

                    print(f"   🤖 LLM Streaming started... (t=0ms)")
                    llm_start = time.time()
                    
                    for token in ask_ai_streaming(text):
                        if my_turn_id != current_turn_id:
                            print("⛔ Barge-in: Stopping LLM stream")
                            return
                        
                        # Track first token time (TTFT - Time To First Token)
                        token_count[0] += 1
                        if first_token_time[0] is None:
                            first_token_time[0] = time.time()
                            ttft = (first_token_time[0] - processing_start_time) * 1000
                            print(f"   ⚡ LLM TTFT: {ttft:.0f}ms (first token received)")

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
                                # Clean the sentence to remove meta-instructions
                                sentence = clean_llm_output(sentence)
                                if not sentence:  # Skip if cleaning removed everything
                                    continue
                                    
                                tts_start = time.time()
                                print(f"   🗣️ TTS: '{sentence}'")
                                for audio_chunk in text_to_speech_streaming(sentence):
                                    if my_turn_id != current_turn_id:
                                        print("⛔ Barge-in: Stopping TTS")
                                        return
                                    
                                    # Track first audio chunk time
                                    if first_audio_time[0] is None:
                                        first_audio_time[0] = time.time()
                                        first_audio_latency = (first_audio_time[0] - processing_start_time) * 1000
                                        print(f"   🔊 First audio chunk ready: {first_audio_latency:.0f}ms from query")
                                    
                                    audio_queue.put(audio_chunk)

                    # Handle remaining text
                    remaining = sentence_buffer.strip()
                    if remaining:
                        # Clean the remaining text
                        remaining = clean_llm_output(remaining)
                        if remaining:  # Only process if something remains after cleaning
                            print(f"   🗣️ TTS final: '{remaining}'")
                            for audio_chunk in text_to_speech_streaming(remaining):
                                if my_turn_id != current_turn_id:
                                    return
                                if first_audio_time[0] is None:
                                    first_audio_time[0] = time.time()
                                    first_audio_latency = (first_audio_time[0] - processing_start_time) * 1000
                                    print(f"   🔊 First audio chunk ready: {first_audio_latency:.0f}ms from query")
                                audio_queue.put(audio_chunk)
                    
                    llm_end_time[0] = time.time()
                    llm_total = (llm_end_time[0] - llm_start) * 1000
                    total_latency = (llm_end_time[0] - processing_start_time) * 1000
                    
                    # Store cleaned response for transcript
                    cleaned_response = clean_llm_output(full_llm_response)
                    agent_response.append(cleaned_response)
                    print(f"   ✅ Full response: {cleaned_response}")
                    print(f"   📊 TIMING: LLM={llm_total:.0f}ms, Tokens={token_count[0]}, Total={total_latency:.0f}ms")

                except Exception as e:
                    print(f"   ❌ Pipeline error: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    processing_done.set()
            
            # Start processing thread
            threading.Thread(target=process_pipeline, daemon=True).start()
            
            # Send audio chunks to client
            chunk_count = 0
            first_chunk_sent = False
            while True:
                if my_turn_id != current_turn_id:
                    print("⛔ Barge-in: Stopping transmission")
                    # Notify client to clear playback
                    try:
                        await ws.send_json({"type": "barge_in"})
                    except:
                        pass
                    break

                try:
                    audio_chunk = audio_queue.get(timeout=0.1)
                    # Mark first chunk so client can clear old audio
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
            
            if my_turn_id == current_turn_id:
                await ws.send_json({"type": "audio_end"})
                audio_end_sent[0] = True
                print(f"✅ Sent {chunk_count} audio chunks")
                
                # Mark that server finished generating - client still playing
                # is_client_playing remains True until playback_complete received
                is_agent_generating[0] = False
                print(f"   📤 All audio sent, waiting for client playback to finish...")
                
                # Add agent response to transcript
                if agent_response:
                    transcript.append({
                        "role": "agent",
                        "text": agent_response[0],
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
                    
                    # Add to conversation history for LLM context
                    add_to_conversation("assistant", agent_response[0])
                    
                    # Check if LLM response indicates end of conversation
                    if detect_end_intent_simple(agent_response[0]):
                        print("👋 Agent response indicates end of call")
                        end_reason[0] = "conversation_complete"
                        call_ended.set()
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
        global current_turn_id
        
        with current_turn_lock:
            current_turn_id += 1
            my_turn_id = current_turn_id
        
        asyncio.run_coroutine_threadsafe(on_text(text, my_turn_id), loop)

    def on_barge_in_callback():
        """Called when STT detects partial speech - immediately interrupt TTS"""
        global current_turn_id
        
        # Trigger barge-in if agent is generating OR client is still playing audio
        if is_agent_generating[0] or is_client_playing[0]:
            with current_turn_lock:
                current_turn_id += 1
            
            # Reset client playing state - we're interrupting
            is_client_playing[0] = False
            
            print("⚡ BARGE-IN: User started speaking, interrupting agent")
            
            # Send barge-in signal to client to stop playback immediately
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send_json({"type": "barge_in"}),
                    loop
                )
            except Exception as e:
                print(f"   ⚠️ Could not send barge_in signal: {e}")

    recognizer, audio_stream = create_streaming_recognizer(on_text_callback, on_barge_in_callback)
    
    # Start call limit monitor
    monitor_task = asyncio.create_task(monitor_call_limits())

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
                    
                    # Only start silence timer if server also finished sending audio
                    # (Don't start timer if new audio is being generated)
                    if audio_end_sent[0] and not is_agent_generating[0]:
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
