# CSV Bulk Calling Feature - Implementation Walkthrough

## Summary

Implemented a complete CSV bulk calling feature that allows users to upload a CSV file with phone numbers and dynamic variables, then automatically initiate calls using FreJun with the selected agent's configuration.

---

## Files Changed

### Backend

| File | Changes |
|------|---------|
| [models.py](file:///d:/Ai-voice/app/db/models.py) | Added `Campaign` and `CampaignCall` models, added `campaign_id` to `Call` |
| [campaigns.py](file:///d:/Ai-voice/app/api/campaigns.py) | **NEW** - Campaign API with start, stop, status, list endpoints |
| [frejun.py](file:///d:/Ai-voice/app/api/frejun.py) | Added `initiate_campaign_call()` function |
| [service.py](file:///d:/Ai-voice/app/db/service.py) | Updated `create_call()` with `campaign_id`, added user info to call history |
| [main.py](file:///d:/Ai-voice/app/main.py) | Registered campaigns router |

### Frontend

| File | Changes |
|------|---------|
| [BulkCampaign.jsx](file:///d:/Ai-voice/frontend/src/components/BulkCampaign.jsx) | **NEW** - Component for CSV upload and campaign management |
| [App.jsx](file:///d:/Ai-voice/frontend/src/App.jsx) | Integrated BulkCampaign in Home page |

---

## Key Features

1. **Agent Selection** - Select which agent to use for the campaign
2. **Variable Extraction** - Auto-detects `{variables}` from agent's system prompt
3. **CSV Validation** - Ensures CSV has `phone_number` and all required variable columns
4. **Progress Tracking** - Real-time updates on campaign progress
5. **Retry Logic** - Failed calls are pushed to end of queue
6. **Configurable Delay** - Default 30s between calls (adjustable)
7. **User Tracking** - All calls linked to user_id for admin visibility

---

## How to Test

1. **Prepare a CSV file:**
```csv
phone_number,customer_name,product
+919876543210,Rahul,Widget Pro
+919876543211,Priya,Widget Basic
```

2. **In the frontend:**
   - Go to Home page
   - Scroll down to "Bulk Calling" section
   - Select an agent
   - Upload your CSV
   - Adjust delay if needed
   - Click "Start Campaign"

3. **Monitor progress:**
   - Watch the progress bar
   - See current call status
   - Check Activity Log for updates

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/campaigns/start` | Start new campaign |
| GET | `/api/campaigns/{id}/status` | Get campaign status |
| POST | `/api/campaigns/{id}/stop` | Stop running campaign |
| GET | `/api/campaigns` | List all campaigns |
