# Access Control & Role-Based Permissions Plan

This document outlines the strategy to implement granular access control, specifically to allow users (like "User 2") to view agents and call history without the ability to create or modify agents.

## 1. Objective
Restrict specific users (e.g., customers/viewers) from performing sensitive actions like:
- Creating new AI Agents
- Editing existing Agent configurations
- Deleting Agents
- Modifying Knowledge Bases

While still allowing them to:
- View the list of Agents
- View Call History
- Listen to Call Recordings
- View Transcripts

## 2. Proposed Role Hierarchy

We will introduce a new role structure to accommodate these restrictions.

| Role | Description | Capabilities |
| :--- | :--- | :--- |
| **`super_admin`** | System Owner | Full access to all organizations and system settings. |
| **`org_admin`** | Organization Admin | Full access within their own organization (Create/Edit Agents, Invite Users). |
| **`editor`** | Standard User | Can create and edit agents within their organization. (Current 'client' behavior). |
| **`viewer`** | **Restricted User** | **Read-Only access.** Can view agents and calls but cannot change anything. |

## 3. Implementation Steps

### Phase 1: Backend Updates (API)

1.  **Update User Model**:
    *   Ensure the `role` field in the database supports the new `viewer` role.
    *   (No schema change needed if `role` is just a string, just new convention).

2.  **Create Permission Dependency**:
    *   Create a reusable FastAPI dependency `get_current_active_user` that also checks permissions.
    *   Example logic:
        ```python
        def check_permissions(user: User, required_permission: str):
            if user.role == 'viewer' and required_permission in ['create', 'edit', 'delete']:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
        ```

3.  **Protect API Endpoints**:
    *   Apply the permission check to sensitive endpoints in `app/api/agents.py`:
        *   `POST /api/agents` (Create) -> Require `editor` or `org_admin` role.
        *   `PUT /api/agents/{id}` (Update) -> Require `editor` or `org_admin` role.
        *   `DELETE /api/agents/{id}` (Delete) -> Require `editor` or `org_admin` role.
    *   `GET` endpoints remain accessible to all authenticated users (including `viewer`).

### Phase 2: Frontend Updates (React)

1.  **Update Auth Context**:
    *   Add helper functions to `AuthContext.jsx` for easy checking:
        ```javascript
        const canEdit = (user) => ['super_admin', 'org_admin', 'editor'].includes(user.role);
        const isViewer = (user) => user.role === 'viewer';
        ```

2.  **Conditional Rendering**:
    *   **Agent List Page (`AgentList.jsx`)**:
        *   Hide the **"+ New Agent"** button if `user.role === 'viewer'`.
        *   Hide/Disable the **"Delete"** button.
    *   **Agent Config Page**:
        *   Make the form **Read-Only** or disable the "Save" button for viewers.
    *   **Dashboard**:
        *   Hide "Settings" or "User Management" links for non-admins.

## 4. How to Apply to "User 2"

Once implemented, the process to restrict "User 2" would be:

1.  **Login as Admin** (Agentx).
2.  **Update User Role**:
    *   Call the update user API (or use database script):
    *   Set `role = 'viewer'` for the user `user2`.
3.  **Verification**:
    *   When `user2` logs in next time:
    *   They see the Agent List.
    *   The "New Agent" button is gone.
    *   They can click an agent to view details, but cannot save changes.

## 5. Security Note

Disabling buttons in the frontend is for **User Experience (UX)**. The real security is enforced by the **Backend API**, ensuring that even if a user manually sends a request (e.g., using Postman/Curl), it will be rejected with `403 Forbidden`.
