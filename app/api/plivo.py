from fastapi import APIRouter, WebSocket
from fastapi.responses import Response

router = APIRouter()

@router.post("/plivo/answer")
async def answer_call():
    xml = """
    <Response>
        <Speak>Welcome to AI Voice Agent</Speak>
    </Response>
    """
    return Response(content=xml, media_type="application/xml")

@router.websocket("/plivo/stream")
async def plivo_stream(ws: WebSocket):
    await ws.accept()
    print("Plivo connected")
