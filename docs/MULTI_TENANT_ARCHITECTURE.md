# Multi-Tenant Architecture Documentation

## Overview

The Anvenssa AI Voice Agent system supports multi-tenancy through an Organization → Agent → User hierarchy.

## Database Schema

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORGANIZATIONS                              │
│  - id (UUID)                                                    │
│  - name (Company Name)                                          │
│  - slug (URL-friendly identifier)                               │
│  - is_active                                                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            │                               │
    ┌───────▼───────┐               ┌───────▼───────┐
    │    USERS      │               │    AGENTS     │
    │ - id          │               │ - id          │
    │ - org_id (FK) │               │ - org_id (FK) │
    │ - username    │               │ - name        │
    │ - role        │               │ - phone_number│
    │ - password    │               │ - system_prompt│
    └───────────────┘               │ - voice       │
                                    │ - language    │
                                    └───────┬───────┘
                                            │
                            ┌───────────────┴───────────────┐
                            │                               │
                    ┌───────▼───────┐               ┌───────▼───────┐
                    │ KNOWLEDGE_BASES│              │     CALLS      │
                    │ - id          │               │ - id           │
                    │ - agent_id    │               │ - agent_id     │
                    │ - name        │               │ - user_id      │
                    │ - chunks      │               │ - transcripts  │
                    └───────────────┘               └────────────────┘
```

## User Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| `super_admin` | System administrator | Full access to all organizations |
| `org_admin` | Organization admin | Full access within their organization |
| `org_member` | Regular user | View-only access within organization |
| `client` | Client user | Limited access for testing |

## Multi-Tenant Data Isolation

### How It Works

1. **User Login**: User authenticates and receives JWT token containing `user_id` and `organization_id`

2. **API Requests**: Every API request includes the JWT token

3. **Data Filtering**: Backend filters all queries by `organization_id`:
   - `/api/agents` → Only returns agents where `agent.organization_id = user.organization_id`
   - `/api/calls/history` → Only returns calls for agents in user's organization

### API Endpoints with Organization Filtering

| Endpoint | Filtering |
|----------|-----------|
| `GET /api/agents` | By logged-in user's organization |
| `POST /api/agents` | Creates under user's organization |
| `GET /api/calls/history` | Only calls from org's agents |
| `GET /api/agents/{id}` | Validates agent belongs to org |

## Implementation Details

### Getting Current User's Organization

```python
from app.api.auth import get_current_user

@app.get("/api/agents")
async def list_agents(current_user: User = Depends(get_current_user)):
    # Filter by user's organization
    agents = agent_service.get_agents_by_organization(current_user.organization_id)
    return {"agents": agents}
```

### Creating Agent Under Organization

```python
@app.post("/api/agents")
async def create_agent(
    request: AgentCreateRequest,
    current_user: User = Depends(get_current_user)
):
    # Use logged-in user's organization
    agent = agent_service.create_agent(
        organization_id=current_user.organization_id,
        name=request.name,
        ...
    )
```

## Security Considerations

1. **Always validate organization ownership** before returning data
2. **Never trust client-provided organization_id** - always use from JWT
3. **Super admins** can bypass organization filtering when needed
4. **Audit logging** should track cross-organization access attempts

## Future Enhancements

- [ ] Organization-level settings (default voice, language)
- [ ] Usage quotas per organization
- [ ] Billing integration per organization
- [ ] Organization-specific analytics dashboard
