from fastapi import APIRouter, WebSocket
from fastapi.responses import Response

router = APIRouter()

@router.post("/from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

@router.post("/twilio/voice")
async def twilio_voice():
    twiml = """
    <Response>
        <Connect>
            <Stream url="wss://abc123.ngrok-free.app/ws/audio" />
        </Connect>
    </Response>
    """
    return Response(content=twiml, media_type="application/xml")
/answer")
async def answer_call():
    xml = """
    <Response>
        <Speak>Welcome to AI Voice Agent</Speak>
    </Response>
    """
    return Response(content=xml, media_type="application/xml")

@router.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket):
    await ws.accept()
    print("twilio connected")
