# from fastapi import FastAPI, WebSocket
# import base64

# from app.services.llm import ask_ai
# from app.services.speech import (
#     text_to_speech,
#     create_streaming_recognizer
# )

# app = FastAPI()

# @app.get("/")
# def health():
#     return {"status": "ok"}

# @app.websocket("/ws/audio")
# async def audio_ws(ws: WebSocket):
#     await ws.accept()
#     print("🔗 WebSocket connected")

#     import asyncio
#     loop = asyncio.get_event_loop()

#     async def on_text(text: str):
#         print("🧑 STT:", text)
#         ai_reply = ask_ai(text)
#         audio = text_to_speech(ai_reply)

#         await ws.send_json({
#             "type": "audio",
#             "data": base64.b64encode(audio).decode()
#         })

#     def on_text_callback(text):
#         asyncio.run_coroutine_threadsafe(on_text(text), loop)

#     recognizer, audio_stream = create_streaming_recognizer(on_text_callback)

#     try:
#         while True:
#             msg = await ws.receive_json()
#             if msg["type"] == "audio":
#                 audio_stream.write(base64.b64decode(msg["data"]))

#     except Exception as e:
#         print("❌ WS closed:", e)
#     finally:
#         recognizer.stop_continuous_recognition()
#         audio_stream.close()
