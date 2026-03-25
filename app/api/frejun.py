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
    agent_id: Optional[str] = None
    user_id: Optional[str] = None


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
                    "agent_id": request.agent_id,
                    "user_id": request.user_id,
                    "status": "initiated",
                    "started_at": datetime.now().isoformat(),
                    "frejun_call_id": frejun_call_id
                }
                
                # Also store by FreJun's call_id for webhook lookups
                if frejun_call_id and frejun_call_id != call_id:
                    active_calls[frejun_call_id] = active_calls[call_id]
                
                # Save call to database with phone numbers and agent
                from app.db.service import call_service
                try:
                    call_record = call_service.create_call(
                        call_provider="frejun",
                        provider_call_id=frejun_call_id,
                        from_number=FREJUN_FROM_NUMBER,
                        to_number=to_number,
                        agent_id=request.agent_id,
                        user_id=request.user_id
                    )
                    print(f"💾 Call saved to database with ID: {call_record.id}")
                except Exception as db_error:
                    print(f"⚠️ Could not save call to database: {db_error}")
                
                print(f"✅ FreJun call initiated: {call_id} (FreJun ID: {frejun_call_id})")
                print(f"   To: {to_number}, From: {FREJUN_FROM_NUMBER}")
                
                return InitiateCallResponse(
                    success=True,
                    call_id=frejun_call_id,  # Return FreJun's call_id for webhook matching
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


async def initiate_campaign_call(
    to_number: str,
    agent_id: str,
    user_id: str,
    campaign_id: str,
    variables: dict = None
) -> dict:
    """
    Initiate a call as part of a bulk calling campaign.
    
    This function:
    1. Calls FreJun API to initiate the call
    2. Creates a Call record linked to the campaign, agent, and user
    3. Applies the agent's prompt variables from the CSV data
    
    Returns dict with success status and call_id
    """
    if not FREJUN_API_KEY:
        return {"success": False, "error": "FreJun API key not configured"}
    
    if not FREJUN_FROM_NUMBER:
        return {"success": False, "error": "FreJun from number not configured"}
    
    # Format phone number
    formatted_number = to_number.strip()
    if not formatted_number.startswith("+"):
        if formatted_number.startswith("91"):
            formatted_number = "+" + formatted_number
        else:
            formatted_number = "+91" + formatted_number.lstrip("0")
    
    # Generate call ID
    import uuid
    call_id = str(uuid.uuid4())[:8]
    
    # Get base URL for flow
    base_url = os.getenv("PUBLIC_BASE_URL", "https://voice.anvenssa.com")
    flow_url = f"{base_url}/api/frejun/flow/{call_id}"
    status_callback_url = f"{base_url}/api/frejun/webhook"
    
    # Store agent and variables info for when the call connects
    active_calls[call_id] = {
        "to_number": formatted_number,
        "from_number": FREJUN_FROM_NUMBER,
        "agent_id": agent_id,
        "user_id": user_id,
        "campaign_id": campaign_id,
        "variables": variables or {},
        "status": "initiated",
        "started_at": datetime.now().isoformat()
    }
    
    frejun_payload = {
        "from_number": FREJUN_FROM_NUMBER,
        "to_number": formatted_number,
        "flow_url": flow_url,
        "status_callback_url": status_callback_url,
        "record": True
    }
    
    print(f"📞 Campaign call: {FREJUN_FROM_NUMBER} → {formatted_number}")
    print(f"   Agent: {agent_id}, Campaign: {campaign_id}")
    
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
                response_data = response.json() if response.text else {}
                frejun_call_id = response_data.get("call_id", call_id)
                
                # Update active call with FreJun ID
                active_calls[call_id]["frejun_call_id"] = frejun_call_id
                if frejun_call_id != call_id:
                    active_calls[frejun_call_id] = active_calls[call_id]
                
                # Save call to database with campaign link
                from app.db.service import call_service
                try:
                    call_record = call_service.create_call(
                        call_provider="frejun",
                        provider_call_id=frejun_call_id,
                        from_number=FREJUN_FROM_NUMBER,
                        to_number=formatted_number,
                        agent_id=agent_id,
                        user_id=user_id,
                        campaign_id=campaign_id
                    )
                    print(f"   💾 Call saved: {call_record.id}")
                    
                    return {
                        "success": True,
                        "call_id": call_record.id,
                        "frejun_call_id": frejun_call_id
                    }
                except Exception as db_error:
                    print(f"   ⚠️ DB error: {db_error}")
                    return {
                        "success": True,  # Call initiated but not saved
                        "call_id": call_id,
                        "frejun_call_id": frejun_call_id,
                        "warning": str(db_error)
                    }
            else:
                error_msg = f"FreJun API error: {response.status_code}"
                print(f"   ❌ {error_msg}")
                return {"success": False, "error": error_msg}
                
    except httpx.TimeoutException:
        return {"success": False, "error": "FreJun API timeout"}
    except Exception as e:
        return {"success": False, "error": str(e)}

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
    
    # Pass agent_id and user_id from active_calls into the WebSocket URL
    # so the FreJun WebSocket handler can load the correct agent config
    query_params = []
    if call_id in active_calls:
        active_calls[call_id]["status"] = "connected"
        call_info = active_calls[call_id]
        if call_info.get("agent_id"):
            query_params.append(f"agent_id={call_info['agent_id']}")
        if call_info.get("user_id"):
            query_params.append(f"user_id={call_info['user_id']}")
        if call_info.get("campaign_id"):
            query_params.append(f"campaign_id={call_info['campaign_id']}")
    
    if query_params:
        ws_url = f"{ws_url}?{'&'.join(query_params)}"
    
    print(f"📋 FreJun requesting flow for call {call_id} ({req.method})")
    print(f"   Returning WebSocket URL: {ws_url}")
    
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
    
    MULTI-TENANT: Looks up the agent by the called phone number (to_number)
    and passes the agent_id in the WebSocket URL for agent-specific handling.
    """
    # Get base URL for WebSocket
    base_url = os.getenv("PUBLIC_BASE_URL", str(req.base_url).rstrip("/"))
    
    # Convert http to wss
    if base_url.startswith("https://"):
        ws_url = base_url.replace("https://", "wss://")
    else:
        ws_url = base_url.replace("http://", "ws://")
    
    # Try to get agent by phone number from request body or query params
    agent_id = None
    to_number = None
    from_number = None
    call_id = None
    
    import sys
    print(f"🔍 DEBUG: Starting agent lookup, method={req.method}", flush=True)
    sys.stdout.flush()
    
    try:
        # Try to get call details from request body (FreJun may POST call info)
        if req.method == "POST":
            print(f"🔍 DEBUG: Parsing POST body...", flush=True)
            try:
                body = await req.json()
                print(f"🔍 DEBUG: Body parsed: {body}", flush=True)
                to_number = body.get("to_number") or body.get("to") or body.get("called_number")
                from_number = body.get("from_number") or body.get("from") or body.get("caller_number")
                call_id = body.get("call_id")
                print(f"📞 Incoming call: from={from_number}, to={to_number}, call_id={call_id}", flush=True)
            except Exception as json_error:
                print(f"   ⚠️ Could not parse JSON body: {json_error}", flush=True)
        else:
            # GET request - check query params
            to_number = req.query_params.get("to_number") or req.query_params.get("to")
            from_number = req.query_params.get("from_number") or req.query_params.get("from")
            call_id = req.query_params.get("call_id")
        
        # Lookup agent by the called phone number
        if to_number:
            from app.db.service import agent_service
            agent = agent_service.get_agent_by_phone(to_number)
            if agent:
                agent_id = agent.id
                print(f"   🤖 Found agent for {to_number}: {agent.name} (ID: {agent_id})")
            else:
                print(f"   ⚠️ No agent configured for phone: {to_number}, using default")
        else:
            print(f"   ⚠️ No to_number provided in request")
    except Exception as e:
        print(f"   ⚠️ Error looking up agent: {e}")
    
    # Build WebSocket URL with optional agent_id
    ws_url = f"{ws_url}/ws/frejun-audio"
    if agent_id:
        ws_url = f"{ws_url}?agent_id={agent_id}"
        if call_id:
            ws_url = f"{ws_url}&call_id={call_id}"
    elif call_id:
        ws_url = f"{ws_url}?call_id={call_id}"
    
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
                # Log full failure details for debugging
                print(f"   ⚠️ Call failure details: {data}")
                failure_reason = data.get("failure_reason") or data.get("reason") or data.get("error")
                if failure_reason:
                    print(f"   ⚠️ Failure reason: {failure_reason}")
        
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
                        # FreJun reports duration in milliseconds, convert to seconds
                        duration_ms = data.get("duration", 0)
                        duration_seconds = int(duration_ms / 1000) if duration_ms > 1000 else duration_ms
                        call_service.end_call(call_id, "completed", duration_seconds)
                        
                        # Trigger sentiment analysis for completed calls
                        try:
                            transcript_content = call_service.get_call_transcript(call_id)
                            if transcript_content:
                                from app.services.sentiment_analysis import analyze_and_save_sentiment
                                call = call_service.get_call_by_provider_id(call_id)
                                agent_id = call.agent_id if call else None
                                print(f"   🎯 Running sentiment analysis for call {call_id}...")
                                analyze_and_save_sentiment(call_id if not call else call.id, transcript_content, agent_id)
                        except Exception as sentiment_error:
                            print(f"   ⚠️ Sentiment analysis failed: {sentiment_error}")
                
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
