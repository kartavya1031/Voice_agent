from fastapi import FastAPI, WebSocket
import base64
import asyncio
import threading
import queue
import re
import json

# Global turn tracking for barge-in support
current_turn_id = 0
current_turn_lock = threading.Lock()

from app.services.llm import ask_ai, ask_ai_streaming
from app.services.speech import (
    text_to_speech,
    text_to_speech_streaming,
    create_streaming_recognizer
)

app = FastAPI()


@app.get("/")
def health():
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def audio_ws(ws: WebSocket):
    await ws.accept()
    print("🔗 WebSocket connected")

    loop = asyncio.get_running_loop()

    async def on_text(text: str, my_turn_id: int):
        global current_turn_id
        
        print("🧑 STT:", repr(text))
        
        # Skip empty or whitespace-only text
        if not text or not text.strip():
            print("⚠️ Empty STT result, skipping...")
            return

        try:
            print("🔄 Starting processing...")
            
            # Using a queue to decouple LLM/TTS generation from WebSocket sending
            audio_queue = queue.Queue()
            processing_done = threading.Event()
            
            def process_pipeline():
                """
                Background thread: 
                1. Stream LLM tokens
                2. Accumulate into full sentences
                3. Send full sentences to TTS
                4. Put audio chunks into queue
                """
                try:
                    sentence_buffer = ""
                    # Split on punctuation to get cleaner sentences for TTS
                    sentence_end_pattern = re.compile(r'[.!?]\s+')
                    
                    full_llm_response = ""

                    print("   🤖 LLM Streaming started...")
                    for token in ask_ai_streaming(text):
                        # Barge-in check
                        if my_turn_id != current_turn_id:
                            print("⛔ Barge-in: Stopping LLM stream")
                            return

                        sentence_buffer += token
                        full_llm_response += token
                        
                        # Check for complete sentence
                        # We use search to find the split point
                        match = sentence_end_pattern.search(sentence_buffer)
                        if match:
                            end_pos = match.end()
                            sentence = sentence_buffer[:end_pos].strip()
                            # Keep the rest for the next sentence
                            sentence_buffer = sentence_buffer[end_pos:]
                            
                            if sentence:
                                print(f"   🗣️ Sending to TTS: '{sentence}'")
                                # Generate audio for this sentence
                                # This function yields chunks of audio bytes
                                for audio_chunk in text_to_speech_streaming(sentence):
                                    if my_turn_id != current_turn_id:
                                        print("⛔ Barge-in: Stopping TTS generation")
                                        return
                                    audio_queue.put(audio_chunk)

                    # Handle any remaining text in buffer (e.g. last sentence without space after)
                    remaining = sentence_buffer.strip()
                    if remaining:
                        print(f"   🗣️ Sending final segment to TTS: '{remaining}'")
                        for audio_chunk in text_to_speech_streaming(remaining):
                            if my_turn_id != current_turn_id:
                                return
                            audio_queue.put(audio_chunk)
                            
                    print(f"   ✅ Entire LLM Response: {full_llm_response}")

                except Exception as e:
                    print(f"   ❌ Pipeline error: {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    processing_done.set()
            
            # Start the processing thread
            threading.Thread(target=process_pipeline, daemon=True).start()
            
            # Main async loop: read from queue and send to WebSocket
            chunk_count = 0
            
            while True:
                # Check for barge-in
                if my_turn_id != current_turn_id:
                    print("⛔ Barge-in: Stopping WebSocket transmission")
                    break

                try:
                    # Non-blocking get with timeout to allow checking loop conditions
                    audio_chunk = audio_queue.get(timeout=0.1)
                    
                    await ws.send_json({
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio_chunk).decode()
                    })
                    chunk_count += 1
                    
                except queue.Empty:
                    # If processing is done and queue is empty, we are finished
                    if processing_done.is_set():
                        break
                    continue
                except Exception as e:
                    print(f"   ❌ WebSocket send error: {e}")
                    break
            
            if my_turn_id == current_turn_id:
                # Only send end signal if we finished naturally (not barged-in)
                await ws.send_json({"type": "audio_end"})
                print(f"✅ Sent {chunk_count} audio chunks")
            else:
                print("⚠️ Transmission aborted due to barge-in")
            
        except Exception as e:
            print(f"❌ Error in on_text: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

    def on_text_callback(text: str):
        global current_turn_id
        
        # Increment turn ID so any running task knows to stop
        with current_turn_lock:
            current_turn_id += 1
            my_turn_id = current_turn_id
        
        # Schedule the async handler
        asyncio.run_coroutine_threadsafe(on_text(text, my_turn_id), loop)

    recognizer, audio_stream = create_streaming_recognizer(on_text_callback)

    try:
        while True:
            msg = await ws.receive_json()

            if msg["type"] == "audio":
                # Receive mic audio
                pcm = base64.b64decode(msg["data"])
                # print("🎧 received bytes:", len(pcm)) # reduced logging
                audio_stream.write(pcm)

    except Exception as e:
        print("❌ WebSocket closed (or connection error):", e)

    finally:
        recognizer.stop_continuous_recognition()
        audio_stream.close()
