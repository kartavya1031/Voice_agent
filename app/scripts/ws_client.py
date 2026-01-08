import asyncio
import websockets
import json
import base64
import simpleaudio as sa

def play_audio(audio_bytes):
    wave = sa.WaveObject(
        audio_bytes,
        num_channels=1,
        bytes_per_sample=2,
        sample_rate=16000
    )
    play = wave.play()
    play.wait_done()


async def main():
    uri = "ws://127.0.0.1:8000/ws/audio"
    async with websockets.connect(
        uri,
        origin="http://127.0.0.1",
        max_size=10 * 1024 * 1024  # 10MB to handle large audio responses
    ) as ws:
        print("🔗 Connected to voice agent")

        while True:
            text = input("You: ")

            await ws.send(json.dumps({
                "type": "text",
                "data": text
            }))

            response = await ws.recv()
            msg = json.loads(response)

            if msg["type"] == "audio":
                audio = base64.b64decode(msg["data"])
                play_audio(audio)


asyncio.run(main())
