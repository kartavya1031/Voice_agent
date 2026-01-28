# API Documentation

## Base URL
- Development: `http://localhost:8000`
- Production: `https://voice.anvenssa.com`

---

## Authentication

### Login
```http
POST /api/auth/login
Content-Type: application/json

{
    "username": "admin",
    "password": "password123"
}
```

**Response:**
```json
{
    "access_token": "eyJ...",
    "token_type": "bearer",
    "user": {
        "id": "uuid",
        "username": "admin",
        "role": "super_admin",
        "organization_id": "uuid"
    }
}
```

---

## Agent Management

### List Agents
```http
GET /api/agents
Authorization: Bearer {token}
```

**Response:**
```json
{
    "agents": [
        {
            "id": "uuid",
            "name": "Sales Agent",
            "organization_id": "uuid",
            "phone_number": "+91XXXXXXXXXX",
            "recognition_language": "en-IN",
            "synthesis_voice_name": "en-IN-NeerjaNeural",
            "is_active": true
        }
    ]
}
```

### Create Agent
```http
POST /api/agents
Authorization: Bearer {token}
Content-Type: application/json

{
    "organization_id": "uuid",
    "name": "New Agent",
    "system_prompt": "You are a helpful assistant...",
    "recognition_language": "en-IN",
    "synthesis_voice_name": "en-IN-NeerjaNeural"
}
```

### Get Agent Details
```http
GET /api/agents/{agent_id}
Authorization: Bearer {token}
```

### Update Agent
```http
PUT /api/agents/{agent_id}
Authorization: Bearer {token}
Content-Type: application/json

{
    "name": "Updated Name",
    "system_prompt": "Updated prompt..."
}
```

### Delete Agent
```http
DELETE /api/agents/{agent_id}
Authorization: Bearer {token}
```

---

## Knowledge Base

### Upload Knowledge Base
```http
POST /api/agents/{agent_id}/knowledge-base
Authorization: Bearer {token}
Content-Type: multipart/form-data

name: "Product FAQ"
file: <file.pdf>
```

### List Knowledge Bases
```http
GET /api/agents/{agent_id}/knowledge-bases
Authorization: Bearer {token}
```

### Delete Knowledge Base
```http
DELETE /api/agents/{agent_id}/knowledge-base/{kb_id}
Authorization: Bearer {token}
```

---

## Call Management

### Get Call History
```http
GET /api/calls/history
Authorization: Bearer {token}
```

**Response:**
```json
{
    "calls": [
        {
            "id": "uuid",
            "agent_id": "uuid",
            "agent_name": "Sales Agent",
            "from_number": "+91XXXXXXXXXX",
            "to_number": "+91YYYYYYYYYY",
            "duration_seconds": 120,
            "status": "completed",
            "recording_url": "https://...",
            "created_at": "2026-01-28T10:00:00Z"
        }
    ],
    "total": 1
}
```

### Get Call Details
```http
GET /api/calls/{call_id}
Authorization: Bearer {token}
```

---

## FreJun Telephony

### Initiate Outbound Call
```http
POST /api/frejun/initiate-call
Authorization: Bearer {token}
Content-Type: application/json

{
    "to_number": "+91XXXXXXXXXX",
    "agent_id": "uuid",
    "record": true
}
```

### Get FreJun Config
```http
GET /api/frejun/config
Authorization: Bearer {token}
```

---

## Voice Settings

### Get Supported Voices
```http
GET /api/agent/voices
```

**Response:**
```json
{
    "languages": [
        {"code": "en-IN", "name": "English (India)"},
        {"code": "hi-IN", "name": "Hindi (India)"}
    ],
    "voices": {
        "en-IN": [
            {"name": "en-IN-NeerjaNeural", "display": "Neerja (Female)"},
            {"name": "en-IN-PrabhatNeural", "display": "Prabhat (Male)"}
        ]
    }
}
```

### Get Prompt Variables
```http
GET /api/agent/prompt-variables
```

---

## WebSocket Endpoints

### Browser Audio WebSocket
```
ws://localhost:8000/ws/audio?agent_id={agent_id}
```

**Messages from client:**
```json
{"type": "audio", "data": "<base64_audio>"}
{"type": "playback_complete"}
{"type": "end_call"}
```

**Messages from server:**
```json
{"type": "audio_chunk", "data": "<base64_audio>", "first_chunk": true}
{"type": "audio_end"}
{"type": "transcript", "speaker": "user", "text": "Hello"}
{"type": "call_ended", "reason": "user_intent"}
```

### FreJun Audio WebSocket
```
ws://localhost:8000/ws/frejun-audio?agent_id={agent_id}&call_id={call_id}
```

---

## Error Responses

All errors follow this format:
```json
{
    "error": "Error message",
    "detail": "Additional details if available"
}
```

| HTTP Code | Meaning |
|-----------|---------|
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing/invalid token |
| 403 | Forbidden - No permission |
| 404 | Not Found - Resource doesn't exist |
| 500 | Server Error - Internal error |
