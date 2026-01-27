"""
Authentication API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.db.service import user_service

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# ============================================================================
# Request/Response Models
# ============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    user: Optional[dict] = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "client"
    display_name: Optional[str] = None
    email: Optional[str] = None


class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UpdatePasswordRequest(BaseModel):
    new_password: str


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate a user"""
    user = user_service.authenticate(request.username, request.password)
    
    if user:
        return LoginResponse(
            success=True,
            message="Login successful",
            user=user
        )
    else:
        return LoginResponse(
            success=False,
            message="Invalid username or password"
        )


@router.post("/logout")
async def logout():
    """Logout endpoint (stateless - just returns success)"""
    return {"success": True, "message": "Logged out successfully"}


@router.get("/users")
async def get_all_users():
    """Get all users (admin only - add auth check in production)"""
    users = user_service.get_all_users()
    return {"users": users}


@router.post("/users")
async def create_user(request: CreateUserRequest):
    """Create a new user (admin only)"""
    user = user_service.create_user(
        username=request.username,
        password=request.password,
        role=request.role,
        display_name=request.display_name,
        email=request.email
    )
    
    if user:
        return {
            "success": True,
            "message": f"User '{request.username}' created successfully",
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "display_name": user.display_name
            }
        }
    else:
        raise HTTPException(
            status_code=400,
            detail=f"User '{request.username}' already exists"
        )


@router.put("/users/{user_id}")
async def update_user(user_id: str, request: UpdateUserRequest):
    """Update a user's details"""
    user = user_service.update_user(
        user_id=user_id,
        display_name=request.display_name,
        email=request.email,
        role=request.role,
        is_active=request.is_active
    )
    
    if user:
        return {"success": True, "message": "User updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")


@router.put("/users/{user_id}/password")
async def update_password(user_id: str, request: UpdatePasswordRequest):
    """Update a user's password"""
    success = user_service.update_password(user_id, request.new_password)
    
    if success:
        return {"success": True, "message": "Password updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")


@router.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Delete a user"""
    success = user_service.delete_user(user_id)
    
    if success:
        return {"success": True, "message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")
