# API Reference & Integration Guide

This document defines the API endpoints and WebSocket protocols for the AI Voice Agent platform.
It is intended for frontend developers and third-party integrators who want to build custom interfaces or connect external services.

## Base URL
- **Local Dev**: `http://localhost:8000`
- **Production**: `https://your-domain.com`

---

## 1. Authentication

The API uses simple session-based or token-based authentication (implementation dependent).

### Login
**POST** `/api/auth/login`

Authenticate a user and retrieve their session/token.

**Request Body:**
```json
{
  "username": "client_user",
  "password": "secure_password"
}
```

**Response:**
```json
{
  "success": true,
  "user": {
    "id": "uuid...",
    "username": "client_user",
    "role": "client",
    "organization_id": "org_uuid..."
  }
}
```

---

## 2. Multi-Tenancy & Filtering

**Crucial Logic**:
- **Admin Users**: Can see all data. Do not need to pass `organization_id`.
- **Client Users**: MUST pass `organization_id` query parameter for all list endpoints (`GET /api/agents`, `GET /api/calls`).
- If a client user tries to access data without `organization_id` or with a wrong ID, the API will return filtered results or empty lists.

---

## 3. Agents API

Manage AI Voice Agents.

### List Agents
**GET** `/api/agents`

**Query Parameters:**
- `organization_id` (Optional): ID of the organization to filter by. Required for non-admin users.

**Response:**
```json
{
  "agents": [
    {
      "id": "agent_uuid...",
      "name": "Sales Bot",
      "phone_number": "+1234567890",
      "synthesis_voice_name": "en-IN-NeerjaNeural",
      "active_kb_id": "kb_uuid..."
    }
  ]
}
```

### Get Agent Details
**GET** `/api/agents/{agent_id}`

Retrieve full configuration for a single agent.

### Create Agent
**POST** `/api/agents`

**Request Body:**
```json
{
  "organization_id": "org_uuid...",
  "name": "Support Bot",
  "system_prompt": "You are a helpful support agent...",
  "sentiment_analysis_prompt": "Analyze if user is satisfied...",
  "synthesis_voice_name": "en-US-JennyNeural"
}
```

---

## 4. Calls API

Access call history, recordings, and transcripts.

### List Calls (History)
**GET** `/api/calls/history`

**Query Parameters:**
- `organization_id` (Optional): Filter by organization.
- `user_id` (Optional): Filter by specific user who made the call.

**Response:**
```json
{
  "calls": [
    {
      "id": "call_uuid...",
      "agent_id": "agent_uuid...",
      "start_time": "2023-10-27T10:00:00Z",
      "status": "completed",
      "duration": 120,
      "sentiment": "Interested",
      "recording_url": "https://..."
    }
  ],
  "total": 50
}
```

### Get Call Details
**GET** `/api/calls/{call_id}`

Returns full details including transcript and sentiment analysis.

**Response:**
```json
{
  "id": "call_uuid...",
  "transcript": [
    { "speaker": "agent", "message": "Hello!" },
    { "speaker": "user", "message": "Hi there." }
  ],
  "sentiment": "Interested",
  "sentiment_details": "{...json analysis...}",
  "recording_url": "https://..."
}
```

---

## 5. WebSocket API (Real-Time Voice Streaming)

This is the core interface for the voice interaction. Any client (Web, Mobile, Telephony Provider) that wants to "talk" to the AI connects here.

**Endpoint**: `ws://YOUR_DOMAIN/ws/audio`

**Query Parameters:**
- `agent_id` (Required): The ID of the agent configuration to load.
- `call_id` (Optional): A unique ID for this call session.

### Protocol Flow

#### 1. Connection
Client opens WebSocket connection to `/ws/audio?agent_id=...`.
Server accepts and loads agent configuration (Voice, Knowledge Base, Prompts).

#### 2. Client -> Server Messages

**A. Start Stream (Optional metadata)**
```json
{
  "type": "start",
  "stream_sid": "stream_123",
  "call_sid": "call_123"
}
```

**B. Audio Data (Continuously sent by client)**
Raw audio chunks captured from microphone.
```json
{
  "event": "media",
  "media": {
    "payload": "<BASE64_ENCODED_G711_ULAW_AUDIO>"
  }
}
```
*Note: Format is typically expected to be **G.711 u-law @ 8000Hz** (standard telephony) or **PCM 16-bit @ 24kHz** depending on server config.*

**C. Stop/Close**
```json
{
  "type": "stop"
}
```

#### 3. Server -> Client Messages

**A. Audio Response (AI Speaking)**
The server streams back generated audio chunks.
```json
{
  "event": "media",
  "media": {
    "payload": "<BASE64_ENCODED_AUDIO_CHUNK>"
  }
}
```
*Client should decode and play these chunks immediately.*

**B. Clear Buffer (Barge-In)**
Sent when the user interrupts the AI. The client MUST immediately stop playing any buffered audio.
```json
{
  "event": "clear"
}
```

**C. Mark (End of Turn)**
Sent when AI finishes a sentence/turn.
```json
{
  "event": "mark",
  "mark": { "name": "end_of_response" }
}
```

---

## 6. Webhooks (Integration with Telephony Providers)

If you are using FreJun or Twilio, configure these Webhooks in their dashboard.

**Unified Webhook URL**: `POST /api/webhooks/frejun`

This single endpoint handles:
1.  **Incoming Call**: `call.initiated`
2.  **Call Status**: `call.ringing`, `call.answered`, `call.completed`
3.  **Recording Ready**: `recording.completed` (Triggers DB update)

**Payload Example (FreJun style):**
```json
{
  "event": "call.completed",
  "data": {
    "call_id": "...",
    "duration": 45,
    "recording_url": "https://..."
  }
}
```
*Note: The server automatically triggers Sentiment Analysis upon receiving the `call.completed` webhook.*
