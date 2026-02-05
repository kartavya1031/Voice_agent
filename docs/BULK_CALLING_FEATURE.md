# CSV Bulk Calling Feature - Implementation Plan

## Overview

Add ability to upload a CSV file containing phone numbers and dynamic variables, then automatically initiate calls to each number using the selected agent's configuration via FreJun.

## User Flow

```
1. User selects an Agent from dropdown on Home page
2. System shows the agent's dynamic variables (from system prompt)
3. User uploads CSV file with columns: phone_number + variable columns
4. System validates CSV has required columns
5. User clicks "Start Campaign"
6. System initiates calls one-by-one via FreJun
7. UI shows real-time progress of the campaign
```

---

## Proposed Changes

### Backend

#### [NEW] `app/api/campaigns.py` - Campaign API endpoints

```python
# Endpoints:
# POST /api/campaigns/start - Start a new bulk calling campaign
# GET /api/campaigns/{id}/status - Get campaign status
# POST /api/campaigns/{id}/stop - Stop a running campaign

# Campaign model tracks:
# - agent_id, csv_data, total_calls, completed_calls
# - status: pending, running, paused, completed, stopped
# - call_queue with per-row status
```

#### [NEW] `app/db/models.py` - Add Campaign model

```python
class Campaign(Base):
    id = Column(String(36), primary_key=True)
    agent_id = Column(String(36), ForeignKey("agents.id"))
    user_id = Column(String(36), ForeignKey("users.id"))  # WHO started the campaign
    organization_id = Column(String(36))  # For admin filtering
    name = Column(String(100))
    total_calls = Column(Integer)
    completed_calls = Column(Integer, default=0)
    successful_calls = Column(Integer, default=0)
    failed_calls = Column(Integer, default=0)
    status = Column(String(20))  # pending/running/completed/stopped
    created_at = Column(TIMESTAMP)
    
    # Relationships
    user = relationship("User")  # To show who started it
    agent = relationship("Agent")
    
class CampaignCall(Base):
    id = Column(String(36), primary_key=True)
    campaign_id = Column(String(36), ForeignKey("campaigns.id"))
    phone_number = Column(String(20))
    variables = Column(Text)  # JSON of dynamic variables
    status = Column(String(20))  # pending/calling/completed/failed
    call_id = Column(String(36), ForeignKey("calls.id"))  # Link to Call history!
    error = Column(Text)
```

#### [MODIFY] `app/db/models.py` - Update Call model

```python
class Call(Base):
    # ... existing fields ...
    user_id = Column(String(36), ForeignKey("users.id"))  # NEW: Who initiated
    campaign_id = Column(String(36), ForeignKey("campaigns.id"))  # NEW: Link to campaign
```

> [!IMPORTANT]
> **Call History Integration**: Every campaign call will be stored in the existing `Call` table with:
> - `user_id` - Who started the campaign
> - `agent_id` - Which agent was used
> - `campaign_id` - Which campaign it belongs to
> 
> **Admin View**: Admin panel will show all calls with a new "Initiated By" column showing the username.

---

### Frontend

#### [MODIFY] `App.jsx` - Add Campaign Section to Home

Add new section with:
1. Agent selector dropdown
2. Dynamic variables display (extracted from agent's system prompt)
3. CSV upload dropzone
4. CSV preview table
5. Start/Stop campaign buttons
6. Real-time progress bar

#### [NEW] `components/BulkCampaign.jsx` - Campaign Component

```jsx
// Features:
// - Select agent → fetch agent details including prompt variables
// - Display required CSV columns based on agent's {variables}
// - CSV file upload with Papa Parse for parsing
// - Validate CSV has phone_number + all required variable columns
// - Start campaign → POST to /api/campaigns/start
// - Poll campaign status and display progress
// - Show call-by-call status in a table
```

---

## CSV Format Example

For an agent with system prompt containing `{customer_name}` and `{company}`:

```csv
phone_number,customer_name,company
+919876543210,Rahul Sharma,ACME Corp
+919876543211,Priya Singh,TechStart Inc
+919876543212,Amit Kumar,GlobalTech
```

---

## API Specifications

### POST /api/campaigns/start

**Request:**
```json
{
  "agent_id": "uuid-here",
  "user_id": "user-uuid",  // Who is starting the campaign
  "name": "Sales Campaign Jan 2026",
  "calls": [
    {
      "phone_number": "+919876543210",
      "variables": {"customer_name": "Rahul", "company": "ACME"}
    },
    ...
  ]
}
```

**Response:**
```json
{
  "success": true,
  "campaign_id": "camp-uuid",
  "total_calls": 100,
  "status": "running"
}
```

### GET /api/campaigns/{id}/status

**Response:**
```json
{
  "id": "camp-uuid",
  "status": "running",
  "total_calls": 100,
  "completed_calls": 45,
  "successful_calls": 42,
  "failed_calls": 3,
  "current_call": {
    "phone_number": "+919876543210",
    "status": "in_progress"
  },
  "calls": [...]
}
```

---

## Call Execution Flow

```
Campaign Started
     ↓
For each row in CSV:
     ↓
1. Get agent config (prompt, voice, KB)
2. Replace {variables} in system prompt with CSV values
3. Initiate FreJun call with to_number
4. Wait for call to complete (via webhook)
5. Update campaign progress
6. Move to next row
     ↓
All calls completed → Mark campaign as "completed"
```

---

## Verification Plan

### Automated Tests
1. Create test CSV with 3 phone numbers
2. Start campaign via API
3. Verify calls initiated in sequence
4. Verify variables replaced in prompts
5. Verify calls appear in call history with user_id

### Manual Verification
1. Upload CSV via UI as user2
2. Observe real-time progress updates
3. Check call history shows campaign calls
4. Verify recordings have correct personalized prompts
5. **Login as Admin → Call History should show "Initiated By: user2"**

---

## Admin Panel Changes

### Call History Table - New Column

| Date | Agent | Number | Duration | Status | **Initiated By** | Actions |
|------|-------|--------|----------|--------|------------------|---------|
| Jan 29 | Sales Agent | +91987... | 2:30 | Completed | **user2** | Play |

The "Initiated By" column will:
- Show username of who started the campaign/call
- Be visible only in admin view (super_admin/org_admin)
- Help track usage per user for billing/analytics

---

## Questions for User Review

> [!IMPORTANT]
> **Before implementing, please confirm:**
> 
> 1. **Call pacing**: Should there be a delay between calls (e.g., 5 seconds)?
> 2. **Failure handling**: If a call fails, should we retry or skip?
> 3. **Parallel calls**: Should we call one at a time or allow 2-3 simultaneous?
> 4. **Campaign limits**: Max calls per campaign? Max campaigns per day?
