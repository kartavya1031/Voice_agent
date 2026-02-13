# SIP Trunking Integration Guide

## Overview

This document covers the SIP trunk integration with FreJun Teler for the AI Voice Agent platform. The integration enables inbound calls via SIP to be routed to AI voice agents without requiring a traditional phone number (DID).

---

## Architecture

```
[Client PBX/Softphone]
        ↓
    SIP INVITE
        ↓
[FreJun SIP Trunk: justcalls_support]
        ↓
    FreJun fetches flow URL
        ↓
[Your App: POST /api/frejun/flow/incoming]
        ↓
    Returns WebSocket URL with agent_id
        ↓
[FreJun connects to /ws/frejun-audio]
        ↓
[AI Voice Conversation via Azure Speech + LLM]
```

---

## FreJun Dashboard Configuration

### SIP Trunk Details

| Setting | Value |
|---------|-------|
| Trunk Name | `justcalls_support` |
| SIP Domain | `justcalls.sip.frejun.ai` |
| Status | Active |
| Channel Limit | 1 concurrent call |
| Recording | Enabled |
| Secure Mode | Enabled (TLS) |

### Webhooks

| Webhook | URL |
|---------|-----|
| Call Status URL | `https://voice.anvenssa.com/api/frejun/webhook` |
| Secret | `frejun-sip-secret` |
| Signature Header | `X-Teler-Signature` |

### Inbound Routing

| Setting | Value |
|---------|-------|
| Routing Name | `ai-voice-routing` |
| Inbound SIP URL | `sip:justcalls.sip.frejun.ai` |

### Authentication

| Setting | Value |
|---------|-------|
| Type | Credential Authentication |
| SIP Username | `manish.varma@anvenssa.com` |
| IP Authentication | Not used |

---

## Database Changes

### Schema Migration

**Date:** February 10, 2026

The `phone_number` column in the `agents` table was expanded to accommodate SIP URIs (which can be longer than traditional phone numbers).

**SQL Command Executed:**
```sql
ALTER TABLE agents MODIFY phone_number VARCHAR(100);
```

**Previous:**
```sql
phone_number VARCHAR(20)  -- Too small for SIP URIs
```

**After:**
```sql
phone_number VARCHAR(100)  -- Supports SIP URIs like "justcalls.sip.frejun.ai"
```

---

## Code Changes

### File: `app/db/models.py`

**Change:** Updated the `Agent` model to reflect the new column size.

**Before:**
```python
# Phone number (unique per agent - for routing incoming calls)
phone_number = Column(String(20), unique=True, nullable=True, index=True)
```

**After:**
```python
# Phone number or SIP URI (unique per agent - for routing incoming calls)
phone_number = Column(String(100), unique=True, nullable=True, index=True)
```

---

## Agent Configuration

### Juztcalls Agent

The agent was configured to respond to incoming SIP calls:

| Field | Value |
|-------|-------|
| Agent ID | `74d442e0-60fd-47bf-93ef-b36d5eb0339c` |
| Name | `Juztcalls Agent` |
| Phone Number | `justcalls.sip.frejun.ai` |
| Organization | `bcc2f4a0-86f5-4c7c-8e0f-55dda615d8f1` |
| Voice | `en-US-SaraNeural` |
| Language | `en-IN` |
| Status | Active |

**API Command Used:**
```bash
curl -X PUT http://localhost:8000/api/agents/74d442e0-60fd-47bf-93ef-b36d5eb0339c \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "justcalls.sip.frejun.ai"}'
```

---

## How Incoming Call Routing Works

### Code Flow

1. **FreJun receives SIP call** to `sip:justcalls.sip.frejun.ai`

2. **FreJun calls your endpoint:**
   ```
   POST /api/frejun/flow/incoming
   Body: {"to_number": "justcalls.sip.frejun.ai", "from_number": "+91...", "call_id": "..."}
   ```

3. **Your app looks up agent by phone number:**
   ```python
   # In app/api/frejun.py line 422-428
   if to_number:
       from app.db.service import agent_service
       agent = agent_service.get_agent_by_phone(to_number)
       if agent:
           agent_id = agent.id
   ```

4. **Returns WebSocket URL with agent_id:**
   ```json
   {
     "action": "stream",
     "ws_url": "wss://voice.anvenssa.com/ws/frejun-audio?agent_id=74d442e0-...",
     "chunk_size": 500,
     "sample_rate": "8k",
     "bargeIn": true
   }
   ```

5. **FreJun connects WebSocket** → AI conversation begins

### Key Files

| File | Purpose |
|------|---------|
| `app/api/frejun.py` | FreJun API integration, incoming call handler |
| `app/db/models.py` | Agent model with phone_number field |
| `app/db/service.py` | `get_agent_by_phone()` lookup function |
| `app/main.py` | WebSocket handler `/ws/frejun-audio` |

---

## Client Handover Information

### SIP Endpoint Details

```
SIP URI: sip:justcalls.sip.frejun.ai
Protocol: SIP over TLS (secure)
Authentication: Credential-based
```

### For PBX Configuration

The client should configure their PBX to route calls to:
```
Destination: justcalls.sip.frejun.ai
Port: 5060 (UDP) or 5061 (TLS)
```

### For Softphone Testing

Configure a SIP softphone (e.g., Linphone, Zoiper) to call:
```
sip:justcalls.sip.frejun.ai
```

---

## Testing & Verification

### Server Logs

When an incoming SIP call is received, you should see:
```
📞 Incoming call: from=+919876543210, to=justcalls.sip.frejun.ai, call_id=abc123
   🤖 Found agent for justcalls.sip.frejun.ai: Juztcalls Agent (ID: 74d442e0-...)
📋 FreJun incoming call request (POST)
   Returning WebSocket URL: wss://voice.anvenssa.com/ws/frejun-audio?agent_id=74d442e0-...
```

### Test Command

Simulate an incoming call:
```bash
curl -X POST https://voice.anvenssa.com/api/frejun/flow/incoming \
  -H "Content-Type: application/json" \
  -d '{"to_number": "justcalls.sip.frejun.ai", "from_number": "+919999999999", "call_id": "test-123"}'
```

**Expected Response:**
```json
{
  "action": "stream",
  "ws_url": "wss://voice.anvenssa.com/ws/frejun-audio?agent_id=74d442e0-60fd-47bf-93ef-b36d5eb0339c&call_id=test-123",
  "chunk_size": 500,
  "sample_rate": "8k",
  "bargeIn": true,
  "barge_in": true,
  "interruptible": true
}
```

---

## Adding More SIP-Enabled Agents

To add another agent that responds to a different SIP trunk:

1. **Create SIP trunk in FreJun** with a new domain (e.g., `sales.sip.frejun.ai`)

2. **Create agent via API:**
   ```bash
   curl -X POST https://voice.anvenssa.com/api/agents \
     -H "Content-Type: application/json" \
     -d '{
       "organization_id": "<org_id>",
       "name": "Sales Agent",
       "phone_number": "sales.sip.frejun.ai",
       "system_prompt": "You are a sales agent...",
       "recognition_language": "en-IN",
       "synthesis_voice_name": "en-IN-NeerjaNeural"
     }'
   ```

3. **Configure FreJun inbound routing** to point to your `/api/frejun/flow/incoming` endpoint

---

## Troubleshooting

### Agent Not Found

**Symptom:** Log shows `⚠️ No agent configured for phone: ...`

**Solution:** Ensure the agent's `phone_number` exactly matches the `to_number` sent by FreJun.

### WebSocket Connection Failed

**Symptom:** FreJun cannot connect to WebSocket

**Solution:** 
1. Verify `PUBLIC_BASE_URL` environment variable is set correctly
2. Check SSL certificate is valid
3. Ensure Caddy/nginx proxy is configured for WebSocket upgrade

### Call Drops Immediately

**Symptom:** Call connects but drops within seconds

**Solution:**
1. Check server logs for errors
2. Verify Azure Speech credentials are valid
3. Check FreJun webhook is receiving events

---

## Summary

| Component | Status |
|-----------|--------|
| SIP Trunk Created | ✅ `justcalls_support` |
| Database Schema Updated | ✅ `phone_number VARCHAR(100)` |
| Model Code Updated | ✅ `app/db/models.py` |
| Agent Configured | ✅ `Juztcalls Agent` |
| Incoming Call Handler | ✅ `/api/frejun/flow/incoming` |
| WebSocket Handler | ✅ `/ws/frejun-audio` |

**SIP Endpoint for Client:** `sip:justcalls.sip.frejun.ai`
