"""
Organization and Agent Management API endpoints
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List
from app.db.service import organization_service, agent_service

router = APIRouter(prefix="/api", tags=["Organizations & Agents"])


# =============================================================================
# Request/Response Models
# =============================================================================

class CreateOrganizationRequest(BaseModel):
    name: str
    slug: Optional[str] = None


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class CreateAgentRequest(BaseModel):
    organization_id: str
    name: str
    description: Optional[str] = None
    phone_number: Optional[str] = None
    system_prompt: Optional[str] = None
    sentiment_analysis_prompt: Optional[str] = None  # Custom conditions for call sentiment analysis
    recognition_language: str = "en-IN"
    synthesis_voice_name: str = "en-IN-NeerjaNeural"
    max_call_duration: int = 600
    max_silence_duration: int = 20


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    phone_number: Optional[str] = None
    system_prompt: Optional[str] = None
    prompt_variables: Optional[str] = None  # JSON string
    sentiment_analysis_prompt: Optional[str] = None  # Custom conditions for call sentiment analysis
    recognition_language: Optional[str] = None
    synthesis_voice_name: Optional[str] = None
    max_call_duration: Optional[int] = None
    max_silence_duration: Optional[int] = None
    active_kb_id: Optional[str] = None
    is_active: Optional[bool] = None


# =============================================================================
# Organization Endpoints
# =============================================================================

@router.get("/organizations")
async def list_organizations():
    """Get all organizations (super admin only)"""
    orgs = organization_service.get_all_organizations()
    return {"organizations": orgs}


@router.post("/organizations")
async def create_organization(request: CreateOrganizationRequest):
    """Create a new organization"""
    org = organization_service.create_organization(
        name=request.name,
        slug=request.slug
    )
    
    if org:
        return {
            "success": True,
            "message": f"Organization '{request.name}' created successfully",
            "organization": {
                "id": org.id,
                "name": org.name,
                "slug": org.slug
            }
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Organization with slug already exists"
        )


@router.get("/organizations/{org_id}")
async def get_organization(org_id: str):
    """Get organization details"""
    org = organization_service.get_organization(org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "is_active": org.is_active,
        "created_at": org.created_at.isoformat() if org.created_at else None
    }


@router.put("/organizations/{org_id}")
async def update_organization(org_id: str, request: UpdateOrganizationRequest):
    """Update organization details"""
    org = organization_service.update_organization(
        org_id=org_id,
        name=request.name,
        is_active=request.is_active
    )
    
    if org:
        return {"success": True, "message": "Organization updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="Organization not found")


@router.delete("/organizations/{org_id}")
async def delete_organization(org_id: str):
    """Delete organization (soft delete)"""
    success = organization_service.delete_organization(org_id)
    
    if success:
        return {"success": True, "message": "Organization deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Organization not found")


# =============================================================================
# Agent Resources Endpoints (Voices, Languages, etc.)
# =============================================================================

@router.get("/agent/voices")
async def get_agent_voices():
    """Get supported recognition languages and synthesis voices"""
    return {
        "languages": [
            {"code": "en-US", "name": "English (US)"},
            {"code": "en-IN", "name": "English (India)"},
            {"code": "hi-IN", "name": "Hindi (India)"},
            {"code": "en-GB", "name": "English (UK)"}
        ],
        "voices": [
            {"shortName": "en-US-AvaNeural", "localName": "Ava", "locale": "en-US", "gender": "Female"},
            {"shortName": "en-US-AndrewNeural", "localName": "Andrew", "locale": "en-US", "gender": "Male"},
            {"shortName": "en-IN-NeerjaNeural", "localName": "Neerja", "locale": "en-IN", "gender": "Female"},
            {"shortName": "en-IN-PrabhatNeural", "localName": "Prabhat", "locale": "en-IN", "gender": "Male"},
            {"shortName": "hi-IN-SwaraNeural", "localName": "Swara", "locale": "hi-IN", "gender": "Female"},
            {"shortName": "hi-IN-MadhurNeural", "localName": "Madhur", "locale": "hi-IN", "gender": "Male"},
            {"shortName": "en-GB-SoniaNeural", "localName": "Sonia", "locale": "en-GB", "gender": "Female"},
            {"shortName": "en-GB-RyanNeural", "localName": "Ryan", "locale": "en-GB", "gender": "Male"}
        ]
    }


@router.get("/agent/prompt-variables")
async def get_prompt_variables():
    """Get available prompt variables"""
    return {
        "variables": {
            "customer_name": "",
            "agent_name": "",
            "company": ""
        },
        "detected_variables": []
    }


# =============================================================================
# Agent Endpoints
# =============================================================================

@router.get("/agents")
async def list_agents(organization_id: Optional[str] = None):
    """
    Get agents. 
    If organization_id is provided, returns agents for that organization.
    Otherwise, returns all agents (super admin only).
    """
    if organization_id:
        agents = agent_service.get_agents_by_organization(organization_id)
    else:
        agents = agent_service.get_all_agents()
    
    return {"agents": agents}


@router.post("/agents")
async def create_agent(request: CreateAgentRequest):
    """Create a new agent for an organization"""
    agent = agent_service.create_agent(
        organization_id=request.organization_id,
        name=request.name,
        description=request.description,
        phone_number=request.phone_number,
        system_prompt=request.system_prompt,
        sentiment_analysis_prompt=request.sentiment_analysis_prompt,
        recognition_language=request.recognition_language,
        synthesis_voice_name=request.synthesis_voice_name,
        max_call_duration=request.max_call_duration,
        max_silence_duration=request.max_silence_duration
    )
    
    if agent:
        return {
            "success": True,
            "message": f"Agent '{request.name}' created successfully",
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "organization_id": agent.organization_id,
                "phone_number": agent.phone_number
            }
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Failed to create agent. Check organization exists and phone number is not in use."
        )


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    """Get agent details"""
    agent = agent_service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    return {
        "id": agent.id,
        "organization_id": agent.organization_id,
        "name": agent.name,
        "description": agent.description,
        "phone_number": agent.phone_number,
        "system_prompt": agent.system_prompt,
        "prompt_variables": agent.prompt_variables,
        "sentiment_analysis_prompt": agent.sentiment_analysis_prompt,
        "recognition_language": agent.recognition_language,
        "synthesis_voice_name": agent.synthesis_voice_name,
        "max_call_duration": agent.max_call_duration,
        "max_silence_duration": agent.max_silence_duration,
        "active_kb_id": agent.active_kb_id,
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat() if agent.created_at else None
    }


@router.get("/agents/{agent_id}/config")
async def get_agent_config(agent_id: str):
    """Get agent configuration for call handling (used by WebSocket handler)"""
    config = agent_service.get_agent_config(agent_id)
    if not config:
        raise HTTPException(status_code=404, detail="Agent not found or inactive")
    
    return config


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, request: UpdateAgentRequest):
    """Update agent configuration"""
    agent = agent_service.update_agent(
        agent_id=agent_id,
        name=request.name,
        description=request.description,
        phone_number=request.phone_number,
        system_prompt=request.system_prompt,
        prompt_variables=request.prompt_variables,
        sentiment_analysis_prompt=request.sentiment_analysis_prompt,
        recognition_language=request.recognition_language,
        synthesis_voice_name=request.synthesis_voice_name,
        max_call_duration=request.max_call_duration,
        max_silence_duration=request.max_silence_duration,
        active_kb_id=request.active_kb_id,
        is_active=request.is_active
    )
    
    if agent:
        return {"success": True, "message": "Agent updated successfully"}
    else:
        raise HTTPException(
            status_code=400,
            detail="Failed to update agent. Check agent exists and phone number is not in use."
        )


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete agent (soft delete)"""
    success = agent_service.delete_agent(agent_id)
    
    if success:
        return {"success": True, "message": "Agent deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Agent not found")


# =============================================================================
# Agent Phone Number Lookup (for call routing)
# =============================================================================

@router.get("/agents/by-phone/{phone_number:path}")
async def get_agent_by_phone(phone_number: str):
    """
    Get agent by phone number (for routing incoming calls).
    The phone number can include + and other characters.
    """
    agent = agent_service.get_agent_by_phone(phone_number)
    if not agent:
        raise HTTPException(
            status_code=404, 
            detail=f"No agent configured for phone number: {phone_number}"
        )
    
    
    config = agent_service.get_agent_config(agent.id)
    return config


# =============================================================================
# Agent Knowledge Base Management
# =============================================================================

@router.post("/agents/{agent_id}/knowledge-base")
async def create_agent_knowledge_base(
    agent_id: str,
    file: UploadFile = File(...),
    name: str = Form(...),
    make_active: bool = Form(True)
):
    """
    Upload a PDF/TXT file and create a new knowledge base for an agent.
    If make_active is True, sets this as the active KB for the agent.
    """
    from fastapi import UploadFile, File, Form
    from app.services.vector_store import create_knowledge_base_from_text, get_kb_file_path
    from app.db.service import kb_service
    import uuid
    import shutil
    import os
    
    # Verify agent exists
    agent = agent_service.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    print(f"📥 KB Upload started for agent {agent.name}: name='{name}', file='{file.filename}'")
    
    try:
        # Generate unique KB ID
        kb_id = str(uuid.uuid4())[:8]
        
        # Read file content
        content = await file.read()
        filename = file.filename or "uploaded_file"
        
        # Save the original file (using global storage structure for now, managed by kb_id)
        file_path = str(get_kb_file_path(kb_id, filename))
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Extract text based on file type
        text_content = ""
        if filename.lower().endswith('.pdf'):
            try:
                import fitz  # PyMuPDF
                with fitz.open(stream=content, filetype="pdf") as pdf_doc:
                    for page in pdf_doc:
                        text_content += page.get_text()
            except ImportError:
                # Fallback: try with pdfplumber
                try:
                    import pdfplumber
                    import io
                    with pdfplumber.open(io.BytesIO(content)) as pdf:
                        for page in pdf.pages:
                            text_content += page.extract_text() or ""
                except ImportError:
                    return {"error": "PDF processing library not installed. Install pymupdf or pdfplumber."}
        elif filename.lower().endswith(('.txt', '.md')):
            text_content = content.decode('utf-8', errors='ignore')
        else:
            return {"error": f"Unsupported file type: {filename}. Supported: .pdf, .txt, .md"}
       
        if not text_content.strip():
            return {"error": "Could not extract text from file"}
       
        # Create knowledge base in vector store (creates collection kb_{kb_id})
        chunk_count = create_knowledge_base_from_text(kb_id, name, text_content)
        
        # Create DB record
        kb = kb_service.create_knowledge_base(
            agent_id=agent_id,
            name=name,
            kb_id=kb_id,
            filename=filename,
            file_path=file_path,
            chunk_count=chunk_count
        )
        
        # Set active if requested
        if make_active:
            agent_service.update_agent(agent_id, active_kb_id=kb_id)
            kb.is_active = True # Update local object for return
            # Note: We should technically update KB record is_active too if we want to track it there
            # But the agent's active_kb_id is the source of truth for what's active.
        
        return {
            "success": True,
            "message": f"Knowledge base '{name}' created successfully",
            "knowledge_base": {
                "id": kb.id,
                "name": kb.name,
                "filename": kb.filename,
                "chunk_count": kb.chunk_count,
                "is_active": make_active
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to process knowledge base: {str(e)}")

@router.get("/agents/{agent_id}/knowledge-bases")
async def list_agent_knowledge_bases(agent_id: str):
    """Get all knowledge bases for an agent"""
    from app.db.service import kb_service
    
    kbs = kb_service.get_agent_knowledge_bases(agent_id)
    return {"knowledge_bases": kbs}

@router.delete("/agents/{agent_id}/knowledge-bases/{kb_id}")
async def delete_agent_knowledge_base(agent_id: str, kb_id: str):
    """Delete a knowledge base"""
    from app.db.service import kb_service
    from app.services.vector_store import delete_knowledge_base
    
    # verify ownership
    kb = kb_service.get_knowledge_base(kb_id)
    if not kb or kb.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    
    # Delete from vector store
    delete_knowledge_base(kb_id)
    
    # Delete from DB
    kb_service.delete_knowledge_base(kb_id)
    
    # access agent to check if active
    agent = agent_service.get_agent(agent_id)
    if agent and agent.active_kb_id == kb_id:
        agent_service.update_agent(agent_id, active_kb_id=None)
        
    return {"success": True, "message": "Knowledge base deleted"}
