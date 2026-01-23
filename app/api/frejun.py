"""
FreJun (Teler) Voice API Integration

This module handles:
1. Initiating outbound calls via FreJun HTTP API
2. Providing call flow endpoint for FreJun to fetch stream configuration
3. Webhook handlers for call status updates
4. WebSocket handler for FreJun media streaming

FreJun Flow:
1. POST /api/frejun/initiate-call → Calls FreJun API to start call
2. FreJun fetches flow from /api/frejun/flow/{call_id}
3. FreJun connects WebSocket to /ws/frejun-audio
4. Audio streams bidirectionally for voice agent conversation
"""

from fastapi import APIRouter, WebSocket, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import httpx
import os
import asyncio
import base64
import time
import re
import threading
import queue
from datetime import datetime

# FreJun API configuration
FREJUN_API_URL = "https://api.frejun.ai/api/v1/calls/initiate"
FREJUN_API_KEY = os.getenv("FREJUN_API_KEY", "")
FREJUN_FROM_NUMBER = os.getenv("FREJUN_FROM_NUMBER", "")  # Your FreJun virtual number

router = APIRouter(prefix="/api/frejun", tags=["FreJun"])

# Store active calls for tracking
active_calls = {}


# ============================================================================
# Request/Response Models
# ============================================================================
class InitiateCallRequest(BaseModel):
    to_number: str
    record: bool = True


class InitiateCallResponse(BaseModel):
    success: bool
    call_id: Optional[str] = None
    message: str


class CallFlowResponse(BaseModel):
    action: str
    ws_url: str
    chunk_size: int = 400
    sample_rate: str = "16k"


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/config")
async def get_frejun_config():
    """Get FreJun configuration status"""
    return {
        "configured": bool(FREJUN_API_KEY and FREJUN_FROM_NUMBER),
        "from_number": FREJUN_FROM_NUMBER if FREJUN_FROM_NUMBER else None,
        "has_api_key": bool(FREJUN_API_KEY)
    }


@router.post("/initiate-call", response_model=InitiateCallResponse)
async def initiate_call(request: InitiateCallRequest, req: Request):
    """
    Initiate an outbound call via FreJun API.
    
    The call flow:
    1. We call FreJun API to initiate call
    2. FreJun calls the to_number
    3. When answered, FreJun fetches our flow_url
    4. We return a WebSocket stream configuration
    5. FreJun connects to our WebSocket for audio streaming
    """
    if not FREJUN_API_KEY:
        raise HTTPException(status_code=400, detail="FreJun API key not configured")
    
    if not FREJUN_FROM_NUMBER:
        raise HTTPException(status_code=400, detail="FreJun from number not configured")
    
    # Format phone number (ensure +91 prefix for India)
    to_number = request.to_number.strip()
    if not to_number.startswith("+"):
        # Assume India number if no country code
        if to_number.startswith("91"):
            to_number = "+" + to_number
        else:
            to_number = "+91" + to_number.lstrip("0")
    
    # Generate unique call ID
    import uuid
    call_id = str(uuid.uuid4())[:8]
    
    # Get the base URL for our server (for callbacks and flow URL)
    # In production, use your public URL or ngrok URL
    base_url = os.getenv("PUBLIC_BASE_URL", str(req.base_url).rstrip("/"))
    
    # Prepare FreJun API request
    flow_url = f"{base_url}/api/frejun/flow/{call_id}"
    status_callback_url = f"{base_url}/api/frejun/webhook"
    
    frejun_payload = {
        "from_number": FREJUN_FROM_NUMBER,
        "to_number": to_number,
        "flow_url": flow_url,
        "status_callback_url": status_callback_url,
        "record": request.record
    }
    
    print(f"📞 Initiating FreJun call: {FREJUN_FROM_NUMBER} → {to_number}")
    print(f"   Flow URL: {flow_url}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                FREJUN_API_URL,
                json=frejun_payload,
                headers={
                    "x-api-key": FREJUN_API_KEY,
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            
            if response.status_code == 202:
                # Parse response to get FreJun's call_id
                response_data = response.json() if response.text else {}
                frejun_call_id = response_data.get("call_id", call_id)
                
                # Store call info in memory (for linking with WebSocket later)
                active_calls[call_id] = {
                    "to_number": to_number,
                    "from_number": FREJUN_FROM_NUMBER,
                    "status": "initiated",
                    "started_at": datetime.now().isoformat(),
                    "frejun_call_id": frejun_call_id
                }
                
                # Also store by FreJun's call_id for webhook lookups
                if frejun_call_id and frejun_call_id != call_id:
                    active_calls[frejun_call_id] = active_calls[call_id]
                
                print(f"✅ FreJun call initiated: {call_id} (FreJun ID: {frejun_call_id})")
                print(f"   To: {to_number}, From: {FREJUN_FROM_NUMBER}")
                
                return InitiateCallResponse(
                    success=True,
                    call_id=call_id,
                    message=f"Call initiated to {to_number}"
                )
            else:
                error_detail = response.text
                print(f"❌ FreJun API error: {response.status_code} - {error_detail}")
                return InitiateCallResponse(
                    success=False,
                    message=f"FreJun API error: {response.status_code}"
                )
                
    except httpx.TimeoutException:
        print("❌ FreJun API timeout")
        return InitiateCallResponse(
            success=False,
            message="FreJun API timeout"
        )
    except Exception as e:
        print(f"❌ FreJun API error: {e}")
        return InitiateCallResponse(
            success=False,
            message=str(e)
        )


@router.api_route("/flow/{call_id}", methods=["GET", "POST"])
async def get_call_flow(call_id: str, req: Request):
    """
    Return the call flow configuration for FreJun.
    
    FreJun calls this endpoint when the call is answered to get
    instructions on how to handle the call (stream, play, hangup).
    
    We return a 'stream' action with our WebSocket URL for audio streaming.
    
    Note: FreJun may use POST method for outbound calls.
    """
    # Get base URL for WebSocket
    base_url = os.getenv("PUBLIC_BASE_URL", str(req.base_url).rstrip("/"))
    
    # Convert http to wss
    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://")
    else:
        ws_url = base_url.replace("http://", "ws://")
    
    ws_url = f"{ws_url}/ws/frejun-audio"
    
    print(f"📋 FreJun requesting flow for call {call_id} ({req.method})")
    print(f"   Returning WebSocket URL: {ws_url}")
    
    # Update call status
    if call_id in active_calls:
        active_calls[call_id]["status"] = "connected"
    
    # Return stream flow configuration with barge-in enabled
    return {
        "action": "stream",
        "ws_url": ws_url,
        "chunk_size": 500,  # 500ms chunks
        "sample_rate": "8k",  # 8kHz for telephony (matches our TTS output)
        "bargeIn": True,  # Enable barge-in support
        "barge_in": True,  # Alternative key for barge-in
        "interruptible": True  # Allow user to interrupt agent
    }


@router.api_route("/flow/incoming", methods=["GET", "POST"])
async def get_incoming_call_flow(req: Request):
    """
    Handle incoming calls from FreJun Voice App.
    This is the Incoming Call URL configured in the FreJun platform.
    """
    # Get base URL for WebSocket
    base_url = os.getenv("PUBLIC_BASE_URL", str(req.base_url).rstrip("/"))
    
    # Convert http to wss
    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://")
    else:
        ws_url = base_url.replace("http://", "ws://")
    
    ws_url = f"{ws_url}/ws/frejun-audio"
    
    print(f"📋 FreJun incoming call request ({req.method})")
    print(f"   Returning WebSocket URL: {ws_url}")
    
    return {
        "action": "stream",
        "ws_url": ws_url,
        "chunk_size": 500,
        "sample_rate": "8k",  # 8kHz for telephony
        "bargeIn": True,  # Enable barge-in support
        "barge_in": True,  # Alternative key for barge-in
        "interruptible": True  # Allow user to interrupt agent
    }


@router.post("/webhook")
async def frejun_webhook(request: Request):
    """
    Handle FreJun webhooks for call status updates.
    
    Events:
    - call.initiated: Call has been initiated
    - call.answered: Call was answered
    - call.completed: Call ended normally
    - call.failed: Call failed
    - stream.initiated: Stream started
    - stream.completed: Stream ended
    - recording.completed: Recording available
    - recording.failed: Recording failed
    """
    from app.db.service import call_service
    
    try:
        body = await request.json()
        event = body.get("event", "unknown")
        data = body.get("data", {})
        call_id = data.get("call_id", "")
        
        print(f"📨 FreJun webhook: {event}")
        print(f"   Data: {data}")
        
        # Update in-memory active calls
        if call_id and call_id in active_calls:
            active_calls[call_id]["status"] = event.replace("call.", "").replace("stream.", "").replace("recording.", "")
            
            if event == "call.completed":
                active_calls[call_id]["duration"] = data.get("duration", 0)
            elif event == "call.failed":
                active_calls[call_id]["failure"] = data.get("failure", {})
        
        # Update database
        if call_id:
            try:
                # Extract phone numbers from webhook data
                from_number = data.get("from") or data.get("from_number")
                to_number = data.get("to") or data.get("to_number")
                
                # Handle call events
                if event.startswith("call."):
                    status = event.replace("call.", "")
                    call_service.update_call_status(call_id, status)
                    
                    # Update phone numbers if available (especially on call.initiated)
                    if from_number or to_number:
                        call_service.update_call_phone_numbers(
                            call_id, 
                            from_number=from_number, 
                            to_number=to_number,
                            provider_call_id=call_id
                        )
                    
                    if event == "call.completed":
                        duration = data.get("duration", 0)
                        call_service.end_call(call_id, "completed", duration)
                
                # Handle stream events
                elif event.startswith("stream."):
                    stream_id = data.get("stream_id")
                    if event == "stream.initiated" and stream_id:
                        call_service.update_call_stream(call_id, stream_id)
                        call_service.update_call_status(call_id, "streaming")
                    elif event == "stream.completed":
                        call_service.update_call_status(call_id, "stream_completed")
                
                # Handle recording events
                elif event.startswith("recording."):
                    recording_url = data.get("recording_url")
                    recording_id = data.get("recording_id")
                    if event == "recording.completed" and recording_url:
                        call_service.update_call_recording(call_id, recording_url, recording_id)
                        print(f"   💾 Recording URL saved: {recording_url[:50]}...")
                    elif event == "recording.failed":
                        call_service.update_call_status(call_id, "recording_failed")
                
            except Exception as db_error:
                print(f"   ⚠️ Database update error: {db_error}")
        
        return {"status": "ok"}
        
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/calls")
async def list_active_calls():
    """List all active/recent calls"""
    return {"calls": active_calls}


@router.get("/calls/{call_id}")
async def get_call_status(call_id: str):
    """Get status of a specific call"""
    if call_id in active_calls:
        return active_calls[call_id]
    raise HTTPException(status_code=404, detail="Call not found")
