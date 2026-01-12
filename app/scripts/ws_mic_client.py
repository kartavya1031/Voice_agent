import asyncio
import websockets
import json
import base64
import sounddevice as sd
import queue
import threading
import numpy as np
import time

SAMPLE_RATE = 16000
CHUNK = 320  # 20 ms
BUFFER_SIZE = 4096

# Queues
mic_audio_queue = queue.Queue()
playback_queue = queue.Queue()

# Flags
is_ai_speaking = False
mic_muted = False  # Mute mic sending while AI speaks to prevent echo loop
last_barge_in_time = 0

print("🚀 ws_mic_client starting")


def playback_worker():
    """
    Dedicated thread for playing audio.
    Blocks on the queue until data arrives, ensuring sequential playback.
    """
    global is_ai_speaking, mic_muted
    
    print("🔊 Playback worker started")
    
    with sd.OutputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='int16',
        blocksize=BUFFER_SIZE
    ) as stream:
        
        while True:
            try:
                audio_chunk = playback_queue.get()
                
                if audio_chunk is None:  # Poison pill
                    break
                
                is_ai_speaking = True
                mic_muted = True  # Mute mic while AI speaks
                
                audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                stream.write(audio_array)
                
                # Check if done speaking
                if playback_queue.empty():
                    time.sleep(0.05)
                    if playback_queue.empty():
                        is_ai_speaking = False
                        mic_muted = False  # Unmute when AI stops
                        print("🎤 Mic active - listening...")

            except Exception as e:
                print(f"⚠️ Playback error: {e}")
                is_ai_speaking = False
                mic_muted = False


def audio_callback(indata, frames, time_info, status):
    """
    Captures mic audio. Only sends to queue if not muted.
    Detects barge-in based on loud volume.
    """
    global is_ai_speaking, mic_muted, last_barge_in_time
    
    # Calculate volume (RMS for int16)
    volume = np.sqrt(np.mean(indata.astype(np.float32)**2))
    
    # Barge-in detection: user speaks loudly while AI is talking
    if is_ai_speaking:
        current_time = time.time()
        THRESHOLD = 2000  # Adjust if needed
        
        if volume > THRESHOLD and (current_time - last_barge_in_time) > 1.0:
            print(f"🔴 BARGE-IN! (Vol: {volume:.0f}) Stopping AI, switching to user...")
            last_barge_in_time = current_time
            
            # 1. Clear playback queue (stop AI audio)
            dropped = 0
            while not playback_queue.empty():
                try:
                    playback_queue.get_nowait()
                    dropped += 1
                except queue.Empty:
                    break
            
            # 2. Unmute mic immediately so new speech goes through
            mic_muted = False
            is_ai_speaking = False
            
            print(f"   Cleared {dropped} chunks. Listening for new query...")
    
    # Only send audio if mic is not muted (prevents echo loop)
    if not mic_muted:
        mic_audio_queue.put(indata.tobytes())


async def send_audio(ws):
    """
    Send mic audio to server (only when not muted)
    """
    loop = asyncio.get_running_loop()
    
    while True:
        try:
            pcm = await loop.run_in_executor(None, mic_audio_queue.get)
            await ws.send(json.dumps({
                "type": "audio",
                "data": base64.b64encode(pcm).decode()
            }))
        except Exception as e:
            print(f"❌ Send error: {e}")
            break


async def receive_audio(ws):
    """
    Receive audio chunks from server and queue for playback
    """
    global is_ai_speaking
    chunk_count = 0

    while True:
        try:
            msg = await ws.recv()
            data = json.loads(msg)

            if data["type"] == "audio_chunk":
                audio_data = base64.b64decode(data["data"])
                playback_queue.put(audio_data)
                
                chunk_count += 1
                if chunk_count == 1:
                    print("🔊 AI responding...")

            elif data["type"] == "audio_end":
                print(f"✅ Received {chunk_count} chunks, waiting for playback to finish...")
                
                # Wait for playback queue to empty (all audio played)
                while not playback_queue.empty():
                    await asyncio.sleep(0.1)
                
                # Small delay to ensure last chunk finishes playing
                await asyncio.sleep(0.3)
                
                print("🔈 Playback complete")
                chunk_count = 0
                
                # Notify server that playback is complete
                try:
                    await ws.send(json.dumps({"type": "playback_complete"}))
                except Exception as e:
                    print(f"   ⚠️ Could not send playback_complete: {e}")
            
            elif data["type"] == "call_end":
                reason = data.get("reason", "unknown")
                print(f"\n📞 CALL ENDED - Reason: {reason}")
                if reason == "max_duration":
                    print("   ⏱️ Maximum call duration reached (5 minutes)")
                elif reason == "silence_timeout":
                    print("   🔇 No speech detected for 10 seconds")
                elif reason == "user_intent":
                    print("   👋 User ended the conversation")
                elif reason == "conversation_complete":
                    print("   ✅ Conversation completed naturally")
                break
                
        except websockets.exceptions.ConnectionClosed:
            print("❌ Connection closed")
            break
        except Exception as e:
            print(f"❌ Receive error: {e}")
            break


async def main():
    global mic_muted
    
    print("🔌 Connecting to WebSocket...")
    
    # Start playback thread
    pb_thread = threading.Thread(target=playback_worker, daemon=True)
    pb_thread.start()

    uri = "ws://127.0.0.1:8000/ws/audio"

    async with websockets.connect(uri, max_size=None) as ws:
        print("🎧 Connected!")

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK,
            callback=audio_callback
        ):
            print("🎤 Microphone active. Speak now!")
            mic_muted = False  # Start with mic active
            
            await asyncio.gather(
                send_audio(ws),
                receive_audio(ws)
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
