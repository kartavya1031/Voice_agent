# from fastapi import APIRouter, WebSocket
# import base64
# import asyncio

# from app.services.llm import ask_ai
# from app.services.speech import text_to_speech

# router = APIRouter()

# @router.websocket("/ws/audio")
# async def audio_ws(ws: WebSocket):
#     await ws.accept()
#     print("🔗 WebSocket connected")

#     try:
#         while True:
#             data = await ws.receive_json()

#             # Expect text for now (audio next)
#             if data["type"] == "text":
#                 user_text = data["data"]
#                 print("🧑 Text received:", user_text)

#                 ai_reply = ask_ai(user_text)
#                 audio = text_to_speech(ai_reply)

#                 audio_b64 = base64.b64encode(audio).decode()

#                 await ws.send_json({
#                     "type": "audio",
#                     "data": audio_b64
#                 })

#     except Exception as e:
#         print("❌ WebSocket closed:", e)
