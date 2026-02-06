"""
Campaign API for Bulk Calling Feature

Handles:
- Starting bulk calling campaigns from CSV data
- Getting campaign status and progress
- Stopping running campaigns
- Campaign execution with sequential calls and retry logic
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict
import asyncio
import json
from datetime import datetime

from app.db.session import SessionLocal
from app.db.models import Campaign, CampaignCall, Call, Agent, User

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])

# Store for running campaign tasks (to enable stopping)
running_campaigns: Dict[str, asyncio.Task] = {}


# =============================================================================
# Request/Response Models
# =============================================================================

class CampaignCallData(BaseModel):
    phone_number: str
    variables: Optional[dict] = {}


class StartCampaignRequest(BaseModel):
    agent_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    call_delay_seconds: int = 30  # Default 30 seconds between calls
    calls: List[CampaignCallData]


class CampaignStatusResponse(BaseModel):
    id: str
    name: str
    status: str
    total_calls: int
    completed_calls: int
    successful_calls: int
    failed_calls: int
    current_call: Optional[dict] = None
    calls: List[dict] = []


# =============================================================================
# Campaign Service Functions
# =============================================================================

def create_campaign(
    agent_id: str,
    user_id: str,
    name: str,
    calls_data: List[CampaignCallData],
    call_delay_seconds: int = 30,
    description: Optional[str] = None
) -> Campaign:
    """Create a new campaign with its calls"""
    db = SessionLocal()
    try:
        # Get user's organization - user must exist (FK constraint)
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f"User {user_id} not found. Please ensure you are logged in with a valid account."
            )
        org_id = user.organization_id
        
        # Create campaign
        campaign = Campaign(
            agent_id=agent_id,
            user_id=user_id,
            organization_id=org_id,
            name=name,
            description=description,
            total_calls=len(calls_data),
            call_delay_seconds=call_delay_seconds,
            status='pending'
        )
        db.add(campaign)
        db.flush()  # Get campaign ID
        
        # Create campaign calls
        for idx, call_data in enumerate(calls_data):
            campaign_call = CampaignCall(
                campaign_id=campaign.id,
                phone_number=call_data.phone_number,
                variables=json.dumps(call_data.variables) if call_data.variables else None,
                queue_position=idx,
                status='pending'
            )
            db.add(campaign_call)
        
        db.commit()
        db.refresh(campaign)
        print(f"✅ Campaign created: {campaign.id} with {len(calls_data)} calls")
        return campaign
    except Exception as e:
        db.rollback()
        print(f"❌ Error creating campaign: {e}")
        raise
    finally:
        db.close()


def get_campaign_status(campaign_id: str) -> dict:
    """Get campaign status with all calls"""
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return None
        
        # Get all campaign calls
        calls = db.query(CampaignCall).filter(
            CampaignCall.campaign_id == campaign_id
        ).order_by(CampaignCall.queue_position).all()
        
        # Find current call (status = 'calling')
        current_call = None
        for c in calls:
            if c.status == 'calling':
                current_call = {
                    "phone_number": c.phone_number,
                    "status": c.status,
                    "attempt_count": c.attempt_count
                }
                break
        
        return {
            "id": campaign.id,
            "name": campaign.name,
            "status": campaign.status,
            "total_calls": campaign.total_calls,
            "completed_calls": campaign.completed_calls,
            "successful_calls": campaign.successful_calls,
            "failed_calls": campaign.failed_calls,
            "call_delay_seconds": campaign.call_delay_seconds,
            "current_call": current_call,
            "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
            "calls": [
                {
                    "id": c.id,
                    "phone_number": c.phone_number,
                    "status": c.status,
                    "attempt_count": c.attempt_count,
                    "error_message": c.error_message,
                    "called_at": c.called_at.isoformat() if c.called_at else None,
                    "completed_at": c.completed_at.isoformat() if c.completed_at else None
                }
                for c in calls
            ]
        }
    finally:
        db.close()


def update_campaign_status(campaign_id: str, status: str):
    """Update campaign status"""
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign:
            campaign.status = status
            if status == 'running' and not campaign.started_at:
                campaign.started_at = datetime.utcnow()
            elif status == 'completed':
                campaign.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def update_campaign_call_status(
    campaign_call_id: str,
    status: str,
    call_id: str = None,
    error_message: str = None
):
    """Update a campaign call's status"""
    db = SessionLocal()
    try:
        cc = db.query(CampaignCall).filter(CampaignCall.id == campaign_call_id).first()
        if cc:
            prev_status = cc.status
            
            # Don't update if already in a final state (prevents re-counting)
            if prev_status in ['completed', 'failed'] and status in ['completed', 'failed']:
                print(f"   ⚠️ Call already {prev_status}, skipping status update to {status}")
                return
            
            cc.status = status
            # Only increment attempt_count when actually calling
            if status == 'calling':
                cc.attempt_count += 1
                cc.called_at = datetime.utcnow()
            if call_id:
                cc.call_id = call_id
            if error_message:
                cc.error_message = error_message
            if status in ['completed', 'failed']:
                cc.completed_at = datetime.utcnow()
            db.commit()
            
            # Update campaign counters only if transitioning TO a final state
            # (not if already in a final state)
            campaign = db.query(Campaign).filter(Campaign.id == cc.campaign_id).first()
            if campaign and status in ['completed', 'failed'] and prev_status not in ['completed', 'failed']:
                campaign.completed_calls += 1
                if status == 'completed':
                    campaign.successful_calls += 1
                else:
                    campaign.failed_calls += 1
                db.commit()
                print(f"   📊 Campaign progress: {campaign.completed_calls}/{campaign.total_calls}")
    finally:
        db.close()


def push_failed_call_to_end(campaign_call_id: str):
    """Push a failed call to the end of the queue for retry"""
    db = SessionLocal()
    try:
        cc = db.query(CampaignCall).filter(CampaignCall.id == campaign_call_id).first()
        if cc:
            # Get max queue position
            max_pos = db.query(CampaignCall).filter(
                CampaignCall.campaign_id == cc.campaign_id
            ).order_by(CampaignCall.queue_position.desc()).first()
            
            new_pos = (max_pos.queue_position + 1) if max_pos else 0
            cc.queue_position = new_pos
            cc.status = 'retry'  # Mark for retry
            db.commit()
            print(f"   ↩️ Pushed call {cc.phone_number} to end of queue (pos: {new_pos})")
    finally:
        db.close()


async def run_campaign(campaign_id: str):
    """
    Execute a campaign - calls each number sequentially with delay.
    Failed calls are pushed to the end of the queue for retry.
    """
    print(f"🚀 Starting campaign execution: {campaign_id}")
    update_campaign_status(campaign_id, 'running')
    
    max_retries = 2  # Maximum retry attempts per call
    
    try:
        # Get campaign details (only once at start)
        db = SessionLocal()
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            print(f"❌ Campaign not found: {campaign_id}")
            db.close()
            return
        
        delay_seconds = campaign.call_delay_seconds
        agent_id = campaign.agent_id
        user_id = campaign.user_id
        total_calls = campaign.total_calls
        db.close()
        
        calls_made = 0
        
        # Process calls in queue order
        while calls_made < total_calls:
            # Use fresh session for each iteration to see latest status
            db = SessionLocal()
            try:
                # Get next pending call
                next_call = db.query(CampaignCall).filter(
                    CampaignCall.campaign_id == campaign_id,
                    CampaignCall.status.in_(['pending', 'retry'])
                ).order_by(CampaignCall.queue_position).first()
                
                if not next_call:
                    print(f"✅ Campaign {campaign_id}: All calls processed")
                    break
                
                # Check if campaign was stopped
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if campaign.status == 'stopped':
                    print(f"⏹️ Campaign {campaign_id} was stopped")
                    break
                
                # Skip if max retries exceeded
                if next_call.attempt_count >= max_retries:
                    update_campaign_call_status(next_call.id, 'failed', error_message='Max retries exceeded')
                    continue
                
                # Store call info before closing session
                call_id = next_call.id
                phone_number = next_call.phone_number
                attempt_count = next_call.attempt_count
                variables = next_call.get_variables_dict()
            finally:
                db.close()
            
            # Make the call (outside the db session)
            print(f"📞 Campaign {campaign_id}: Calling {phone_number} (attempt {attempt_count + 1})")
            update_campaign_call_status(call_id, 'calling')
            
            try:
                # Import here to avoid circular imports
                from app.api.frejun import initiate_campaign_call
                
                # Make the call via FreJun
                # NOTE: FreJun API is async - success means FreJun ACCEPTED the request,
                # not that the call has completed. The actual call happens via WebSocket.
                call_result = await initiate_campaign_call(
                    to_number=phone_number,
                    agent_id=agent_id,
                    user_id=user_id,
                    campaign_id=campaign_id,
                    variables=variables
                )
                
                if call_result.get('success'):
                    # Mark as completed - FreJun accepted the call request
                    update_campaign_call_status(
                        call_id, 
                        'completed',
                        call_id=call_result.get('call_id')
                    )
                    print(f"   ✅ Call initiated: {call_result.get('call_id')}")
                    calls_made += 1
                else:
                    # Call failed to initiate - push to end for retry
                    error_msg = call_result.get('error', 'Call failed')
                    print(f"   ❌ Call initiation failed: {error_msg}")
                    update_campaign_call_status(
                        call_id,
                        'pending',  # Reset to pending
                        error_message=error_msg
                    )
                    push_failed_call_to_end(call_id)
                    
            except Exception as e:
                print(f"   ❌ Call exception: {e}")
                update_campaign_call_status(
                    call_id,
                    'pending',
                    error_message=str(e)
                )
                push_failed_call_to_end(call_id)
            
            # Wait before next call
            print(f"   ⏳ Waiting {delay_seconds}s before next call...")
            await asyncio.sleep(delay_seconds)
        
        # Mark campaign complete
        update_campaign_status(campaign_id, 'completed')
        print(f"🎉 Campaign {campaign_id} completed!")
        
    except Exception as e:
        print(f"❌ Campaign execution error: {e}")
        import traceback
        traceback.print_exc()
        update_campaign_status(campaign_id, 'failed')
    finally:
        # Remove from running campaigns
        if campaign_id in running_campaigns:
            del running_campaigns[campaign_id]


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/start")
async def start_campaign(request: StartCampaignRequest, background_tasks: BackgroundTasks):
    """
    Start a new bulk calling campaign.
    
    The campaign will run in the background, calling each number sequentially
    with the configured delay between calls.
    """
    # Validate agent exists
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.id == request.agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
    finally:
        db.close()
    
    # Create campaign
    campaign = create_campaign(
        agent_id=request.agent_id,
        user_id=request.user_id,
        name=request.name,
        calls_data=request.calls,
        call_delay_seconds=request.call_delay_seconds,
        description=request.description
    )
    
    # Start campaign execution in background
    task = asyncio.create_task(run_campaign(campaign.id))
    running_campaigns[campaign.id] = task
    
    return {
        "success": True,
        "campaign_id": campaign.id,
        "total_calls": campaign.total_calls,
        "status": "running",
        "message": f"Campaign started with {campaign.total_calls} calls"
    }


@router.get("/{campaign_id}/status")
async def get_status(campaign_id: str):
    """Get the current status of a campaign"""
    status = get_campaign_status(campaign_id)
    if not status:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return status


@router.post("/{campaign_id}/stop")
async def stop_campaign(campaign_id: str):
    """Stop a running campaign"""
    update_campaign_status(campaign_id, 'stopped')
    
    # Cancel the background task if running
    if campaign_id in running_campaigns:
        running_campaigns[campaign_id].cancel()
        del running_campaigns[campaign_id]
    
    return {
        "success": True,
        "message": "Campaign stopped"
    }


@router.get("/")
async def list_campaigns(user_id: Optional[str] = None, organization_id: Optional[str] = None):
    """
    List campaigns.
    - If organization_id provided: returns campaigns for that org
    - If user_id provided: returns campaigns for that user
    - Otherwise: returns all campaigns (admin only)
    """
    db = SessionLocal()
    try:
        query = db.query(Campaign)
        
        if organization_id:
            query = query.filter(Campaign.organization_id == organization_id)
        elif user_id:
            query = query.filter(Campaign.user_id == user_id)
        
        campaigns = query.order_by(Campaign.created_at.desc()).limit(50).all()
        
        return {
            "campaigns": [
                {
                    "id": c.id,
                    "name": c.name,
                    "status": c.status,
                    "total_calls": c.total_calls,
                    "completed_calls": c.completed_calls,
                    "successful_calls": c.successful_calls,
                    "failed_calls": c.failed_calls,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "agent_name": c.agent.name if c.agent else None,
                    "user_name": c.user.display_name if c.user else None
                }
                for c in campaigns
            ]
        }
    finally:
        db.close()
