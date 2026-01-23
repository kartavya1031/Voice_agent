"""
FreJun Webhooks API

This module handles FreJun webhook events for:
1. Stream events (stream.initiated, stream.completed)
2. Recording events (recording.completed, recording.failed)

These webhooks are called by FreJun to notify about stream and recording status.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime

from app.db.service import call_service

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


# ============================================================================
# Stream Webhooks
# ============================================================================

@router.post("/stream")
async def handle_stream_webhook(request: Request):
    """
    Handle FreJun stream webhook events.
    
    Events:
    - stream.initiated: A new media stream has been initiated
    - stream.completed: A stream has been torn down
    
    Sample Payload (stream.initiated):
    {
        "event": "stream.initiated",
        "account_id": uuid,
        "call_app_id": uuid,
        "data": {
            "call_id": uuid,
            "stream_id": uuid,
            "start_time": timestamp
        }
    }
    
    Sample Payload (stream.completed):
    {
        "event": "stream.completed",
        "account_id": uuid,
        "call_app_id": uuid,
        "data": {
            "call_id": uuid,
            "stream_id": uuid,
            "end_time": timestamp
        }
    }
    """
    try:
        body = await request.json()
        event = body.get("event", "unknown")
        account_id = body.get("account_id")
        call_app_id = body.get("call_app_id")
        data = body.get("data", {})
        
        call_id = data.get("call_id")
        stream_id = data.get("stream_id")
        
        print(f"📡 Stream Webhook: {event}")
        print(f"   Account ID: {account_id}")
        print(f"   Call App ID: {call_app_id}")
        print(f"   Call ID: {call_id}")
        print(f"   Stream ID: {stream_id}")
        print(f"   Data: {data}")
        
        if event == "stream.initiated":
            start_time = data.get("start_time")
            print(f"   ▶️ Stream initiated at {start_time}")
            
            # Update call with stream ID
            if call_id:
                call_service.update_call_stream(call_id, stream_id)
                call_service.update_call_status(call_id, "streaming")
            
            return {"status": "ok", "message": "Stream initiated event processed"}
            
        elif event == "stream.completed":
            end_time = data.get("end_time")
            print(f"   ⏹️ Stream completed at {end_time}")
            
            # Update call status
            if call_id:
                call_service.update_call_status(call_id, "stream_completed")
            
            return {"status": "ok", "message": "Stream completed event processed"}
        
        else:
            print(f"   ⚠️ Unknown stream event: {event}")
            return {"status": "ok", "message": f"Unknown event: {event}"}
            
    except Exception as e:
        print(f"❌ Stream Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


# ============================================================================
# Recording Webhooks
# ============================================================================

@router.post("/recording")
async def handle_recording_webhook(request: Request):
    """
    Handle FreJun recording webhook events.
    
    Events:
    - recording.completed: A recording is available
    - recording.failed: A recording has failed
    
    Sample Payload (recording.completed):
    {
        "event": "recording.completed",
        "account_id": uuid,
        "data": {
            "call_id": uuid,
            "recording_id": uuid,
            "recording_url": string
        }
    }
    
    Sample Payload (recording.failed):
    {
        "event": "recording.failed",
        "account_id": uuid,
        "data": {
            "call_id": uuid,
            "recording_id": uuid
        }
    }
    """
    try:
        body = await request.json()
        event = body.get("event", "unknown")
        account_id = body.get("account_id")
        data = body.get("data", {})
        
        call_id = data.get("call_id")
        recording_id = data.get("recording_id")
        recording_url = data.get("recording_url")
        
        print(f"🎙️ Recording Webhook: {event}")
        print(f"   Account ID: {account_id}")
        print(f"   Call ID: {call_id}")
        print(f"   Recording ID: {recording_id}")
        print(f"   Recording URL: {recording_url}")
        
        if event == "recording.completed":
            print(f"   ✅ Recording completed and available")
            
            # Update call with recording URL
            if call_id and recording_url:
                call_service.update_call_recording(
                    call_id=call_id,
                    recording_url=recording_url,
                    recording_id=recording_id
                )
                print(f"   💾 Recording URL saved to database")
            
            return {"status": "ok", "message": "Recording completed event processed"}
            
        elif event == "recording.failed":
            print(f"   ❌ Recording failed for call {call_id}")
            
            # Update call status to indicate recording failure
            if call_id:
                call_service.update_call_status(call_id, "recording_failed")
            
            return {"status": "ok", "message": "Recording failed event processed"}
        
        else:
            print(f"   ⚠️ Unknown recording event: {event}")
            return {"status": "ok", "message": f"Unknown event: {event}"}
            
    except Exception as e:
        print(f"❌ Recording Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


# ============================================================================
# Unified Webhook Endpoint (for single URL configuration)
# ============================================================================

@router.post("/frejun")
async def handle_frejun_unified_webhook(request: Request):
    """
    Unified webhook endpoint that handles all FreJun webhook events.
    
    This allows configuring a single webhook URL in FreJun that handles:
    - call.initiated, call.answered, call.completed, call.failed
    - stream.initiated, stream.completed
    - recording.completed, recording.failed
    """
    try:
        body = await request.json()
        event = body.get("event", "unknown")
        
        print(f"📨 FreJun Unified Webhook: {event}")
        
        # Route to appropriate handler based on event type
        if event.startswith("stream."):
            return await handle_stream_webhook(request)
        elif event.startswith("recording."):
            return await handle_recording_webhook(request)
        elif event.startswith("call."):
            # Handle call events
            data = body.get("data", {})
            call_id = data.get("call_id")
            
            print(f"   Call ID: {call_id}")
            print(f"   Data: {data}")
            
            status_map = {
                "call.initiated": "initiated",
                "call.ringing": "ringing",
                "call.answered": "answered",
                "call.completed": "completed",
                "call.failed": "failed"
            }
            
            if event in status_map and call_id:
                call_service.update_call_status(call_id, status_map[event])
                
                # If call completed, update duration
                if event == "call.completed":
                    duration = data.get("duration")
                    if duration and call_id:
                        from app.db.service import call_service
                        call_service.end_call(call_id, "completed", duration)
            
            return {"status": "ok", "message": f"{event} event processed"}
        else:
            print(f"   ⚠️ Unknown event type: {event}")
            return {"status": "ok", "message": f"Unknown event: {event}"}
            
    except Exception as e:
        print(f"❌ Unified Webhook error: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )
