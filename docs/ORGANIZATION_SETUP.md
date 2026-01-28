# Organization Setup Guide

## Setting Up Multi-Tenant Organizations

This guide explains how to create organizations and users for multi-tenant isolation.

---

## 1. Create an Organization

Currently, organizations can be created via the database or API. Here's how to create one:

### Via Database (SQLite)
```sql
INSERT INTO organizations (id, name, slug, is_active, created_at, updated_at)
VALUES (
    'org-uuid-here',
    'ACME Corporation',
    'acme',
    1,
    datetime('now'),
    datetime('now')
);
```

### Via Python Script
```python
from app.db.service import organization_service

org = organization_service.create_organization(
    name="ACME Corporation",
    slug="acme"
)
print(f"Created org: {org.id}")
```

---

## 2. Create a User for the Organization

### Via API
```http
POST /api/auth/users
Content-Type: application/json

{
    "username": "acme_admin",
    "password": "SecurePassword123",
    "role": "org_admin",
    "display_name": "ACME Admin",
    "email": "admin@acme.com",
    "organization_id": "org-uuid-from-step-1"
}
```

### Response
```json
{
    "success": true,
    "message": "User 'acme_admin' created successfully",
    "user": {
        "id": "user-uuid",
        "username": "acme_admin",
        "role": "org_admin",
        "display_name": "ACME Admin",
        "organization_id": "org-uuid"
    }
}
```

---

## 3. Create Agents for the Organization

When the user logs in and creates agents, they will automatically be linked to their organization.

### Via API (with organization context)
```http
POST /api/agents
Content-Type: application/json

{
    "organization_id": "org-uuid",
    "name": "ACME Sales Agent",
    "system_prompt": "You are a sales agent for ACME...",
    "recognition_language": "en-US",
    "synthesis_voice_name": "en-US-JennyNeural"
}
```

---

## 4. How Isolation Works

Once set up, multi-tenant isolation works as follows:

### Login
1. User logs in with their credentials
2. Backend returns user info **including organization_id**
3. Frontend stores organization_id in session

### Data Access
1. When user requests agents: `GET /api/agents?organization_id={user.org_id}`
   - Only agents belonging to their organization are returned
   
2. When user views call history: `GET /api/calls/history?organization_id={user.org_id}`
   - Only calls from their organization's agents are returned

### Data Creation
1. When user creates an agent: `POST /api/agents`
   - Agent is automatically linked to user's organization
   
2. When calls are made: The call is linked to the agent
   - This creates the organization → agent → call chain

---

## 5. Role Hierarchy

| Role | Description | Access |
|------|-------------|--------|
| `super_admin` | System administrator | All organizations |
| `org_admin` | Organization admin | Full access to own organization |
| `org_member` | Regular employee | Read access to own organization |
| `client` | External client | Limited testing access |

---

## 6. Example: Complete Setup Flow

```bash
# Step 1: Create Organization (via database CLI)
sqlite3 app/data/voice_agent.db

INSERT INTO organizations (id, name, slug, is_active, created_at, updated_at)
VALUES (
    'org-001-acme',
    'ACME Corporation',
    'acme',
    1,
    datetime('now'),
    datetime('now')
);

# Step 2: Create User via API
curl -X POST http://localhost:8000/api/auth/users \
  -H "Content-Type: application/json" \
  -d '{
    "username": "acme_user",
    "password": "SecurePass123",
    "role": "org_admin",
    "organization_id": "org-001-acme"
  }'

# Step 3: Login as the new user
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "acme_user", "password": "SecurePass123"}'

# Response includes organization_id for filtering
```

---

## 7. Verification

After setup, verify isolation is working:

1. **Login as User A** (Organization: ACME)
   - Check agent list shows only ACME agents
   - Check call history shows only ACME calls

2. **Login as User B** (Organization: Globex)
   - Check agent list shows only Globex agents
   - Check call history shows only Globex calls

3. **Login as super_admin** (No organization)
   - Should see all agents and calls across all organizations

---

## Troubleshooting

### User can't see any agents
- Verify `organization_id` is set on the user record
- Verify agents have the same `organization_id`
- Check browser console for API responses

### Call history is empty
- Verify calls have an `agent_id` set
- Verify the agent belongs to the user's organization
- Check the API is receiving the `organization_id` parameter
