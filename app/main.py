from fastapi import FastAPI, WebSocket
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
from datetime import datetime
from pathlib import Path
from typing import Optional

# Global turn tracking for barge-in support
current_turn_id = 0
current_turn_lock = threading.Lock()

from app.services.llm import ask_ai, ask_ai_streaming
from app.services.speech import (
    text_to_speech,
    text_to_speech_streaming,
    create_streaming_recognizer
)

app = FastAPI(title="Anvenssa Voice Agent API")

# CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/api/transcripts")
def list_transcripts():
    """List all saved transcripts"""
    transcript_dir = Path(__file__).parent / "transcripts"
    if not transcript_dir.exists():
        return {"transcripts": []}
    
    transcripts = []
    for f in sorted(transcript_dir.glob("*.txt"), reverse=True):
        transcripts.append({
            "filename": f.name,
            "created": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "size": f.stat().st_size
        })
    return {"transcripts": transcripts}

@app.get("/api/transcripts/{filename}")
def get_transcript(filename: str):
    """Get a specific transcript content"""
    transcript_dir = Path(__file__).parent / "transcripts"
    filepath = transcript_dir / filename
    
    if not filepath.exists() or not filepath.is_file():
        return {"error": "Transcript not found"}
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    return {"filename": filename, "content": content}

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


def save_transcript(transcript: list, call_duration: float):
    """Save call transcript to file"""
    # Create transcripts directory if it doesn't exist
    transcript_dir = Path(__file__).parent / "transcripts"
    transcript_dir.mkdir(exist_ok=True)
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = transcript_dir / f"call_{timestamp}.txt"
    
    # Format transcript
    content = []
    content.append("=" * 60)
    content.append(f"CALL TRANSCRIPT")
    content.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content.append(f"Duration: {call_duration:.1f} seconds")
    content.append("=" * 60)
    content.append("")
    
    for entry in transcript:
        role = entry["role"].upper()
        text = entry["text"]
        timestamp = entry["timestamp"]
        content.append(f"[{timestamp}] {role}:")
        content.append(f"  {text}")
        content.append("")
    
    content.append("=" * 60)
    content.append("END OF TRANSCRIPT")
    content.append("=" * 60)
    
    # Save to file
    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(content))
    
    print(f"📝 Transcript saved: {filename}")
    return filename


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
    is_agent_speaking = [False]  # Track if agent is currently responding
    transcript = []
    call_ended = threading.Event()
    end_reason = [None]  # Mutable container for end reason
    
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
            
            # Check silence timeout - ONLY after CLIENT finishes playing audio
            # Don't count silence while agent is speaking or audio is still playing
            if not is_agent_speaking[0] and last_playback_complete_time[0] is not None:
                silence_since_playback = current_time - last_playback_complete_time[0]
                
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
            
            # Mark that agent is speaking (silence timer should pause)
            is_agent_speaking[0] = True
            last_playback_complete_time[0] = None  # Reset until client finishes playback
            
            audio_queue = queue.Queue()
            processing_done = threading.Event()
            agent_response = []  # Collect full response for transcript
            
            def process_pipeline():
                """Background thread: LLM → sentence detection → TTS → audio queue"""
                try:
                    sentence_buffer = ""
                    sentence_end_pattern = re.compile(r'[.!?]\s+')
                    full_llm_response = ""

                    print("   🤖 LLM Streaming started...")
                    for token in ask_ai_streaming(text):
                        if my_turn_id != current_turn_id:
                            print("⛔ Barge-in: Stopping LLM stream")
                            return

                        sentence_buffer += token
                        full_llm_response += token
                        
                        match = sentence_end_pattern.search(sentence_buffer)
                        if match:
                            end_pos = match.end()
                            sentence = sentence_buffer[:end_pos].strip()
                            sentence_buffer = sentence_buffer[end_pos:]
                            
                            if sentence:
                                print(f"   🗣️ TTS: '{sentence}'")
                                for audio_chunk in text_to_speech_streaming(sentence):
                                    if my_turn_id != current_turn_id:
                                        print("⛔ Barge-in: Stopping TTS")
                                        return
                                    audio_queue.put(audio_chunk)

                    # Handle remaining text
                    remaining = sentence_buffer.strip()
                    if remaining:
                        print(f"   🗣️ TTS final: '{remaining}'")
                        for audio_chunk in text_to_speech_streaming(remaining):
                            if my_turn_id != current_turn_id:
                                return
                            audio_queue.put(audio_chunk)
                    
                    agent_response.append(full_llm_response)
                    print(f"   ✅ Full response: {full_llm_response}")

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
                print(f"✅ Sent {chunk_count} audio chunks")
                
                # Mark that agent finished sending - but silence timer starts when client confirms playback complete
                is_agent_speaking[0] = False
                print(f"   📤 All audio sent, waiting for client playback to finish...")
                
                # Add agent response to transcript
                if agent_response:
                    transcript.append({
                        "role": "agent",
                        "text": agent_response[0],
                        "timestamp": datetime.now().strftime("%H:%M:%S")
                    })
                    
                    # Check if LLM response indicates end of conversation
                    if detect_end_intent_simple(agent_response[0]):
                        print("👋 Agent response indicates end of call")
                        end_reason[0] = "conversation_complete"
                        call_ended.set()
            else:
                # Barge-in happened - still mark as not speaking
                is_agent_speaking[0] = False
            
        except Exception as e:
            print(f"❌ Error in on_text: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            # Ensure flag is reset on error
            is_agent_speaking[0] = False

    def on_text_callback(text: str):
        global current_turn_id
        
        with current_turn_lock:
            current_turn_id += 1
            my_turn_id = current_turn_id
        
        asyncio.run_coroutine_threadsafe(on_text(text, my_turn_id), loop)

    recognizer, audio_stream = create_streaming_recognizer(on_text_callback)
    
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
                    # Client finished playing all audio - NOW start silence timer
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
        
        # Save transcript
        if transcript:
            save_transcript(transcript, call_duration)
        
        print(f"📞 Call ended. Duration: {call_duration:.1f}s, Reason: {end_reason[0]}")
