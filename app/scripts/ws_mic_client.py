import asyncio
import websockets
import json
import base64
import sounddevice as sd
import simpleaudio as sa
import queue

SAMPLE_RATE = 16000
CHUNK = 320  # 20 ms (16000 * 0.02)

audio_queue = queue.Queue()

print("🚀 ws_mic_client starting")


def play_audio(audio_bytes):
    wave = sa.WaveObject(
        audio_bytes,
        num_channels=1,
        bytes_per_sample=2,
        sample_rate=16000
    )
    wave.play().wait_done()


def audio_callback(indata, frames, time, status):
    """
    Runs in a separate thread.
    DO NOT use asyncio here.
    """
    if status:
        print("⚠️", status)
    audio_queue.put(indata.tobytes())


async def send_audio(ws):
    """
    Sends mic audio chunks to server
    """
    loop = asyncio.get_running_loop()

    while True:
        pcm = await loop.run_in_executor(None, audio_queue.get)

        await ws.send(json.dumps({
            "type": "audio",
            "data": base64.b64encode(pcm).decode()
        }))


async def receive_audio(ws):
    """
    Receives AI audio and plays it
    """
    while True:
        msg = await ws.recv()
        data = json.loads(msg)

        if data["type"] == "audio":
            play_audio(base64.b64decode(data["data"]))


async def main():
    print("🔌 Connecting to WebSocket...")

    uri = "ws://127.0.0.1:8000/ws/audio"

    async with websockets.connect(uri, max_size=20 * 1024 * 1024) as ws:
        print("🎧 WebSocket connected, initializing microphone...")

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK,
            device=1,  # default microphone
            callback=audio_callback
        )

        stream.start()
        print("🎤 Microphone streaming started")

        await asyncio.gather(
            send_audio(ws),
            receive_audio(ws)
        )


if __name__ == "__main__":
    asyncio.run(main())
