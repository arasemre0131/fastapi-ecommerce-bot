from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from .schemas import (
    UserCreate, UserResponse, UserUpdate, Token, RefreshTokenRequest,
    PasswordResetRequest, PasswordResetConfirm, ChangePasswordRequest,
    APIKeyCreate, APIKeyResponse, APIKeyList
)
from .service import user_service, token_service, api_key_service
from .dependencies import get_current_user, get_current_superuser, check_api_key_rate_limit
from ..core.database import get_db
from ..core.exceptions import AuthenticationException, ValidationException


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_create: UserCreate,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user"""
    try:
        user = await user_service.create_user(db, user_create)
        return UserResponse.model_validate(user)
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """Login user and return tokens"""
    try:
        # Get client IP for security logging
        client_ip = request.client.host if request.client else "unknown"
        
        # Authenticate user
        user = await user_service.authenticate_user(
            db, form_data.username, form_data.password, client_ip
        )
        if not user:
            raise AuthenticationException("Invalid email or password")
        
        # Create tokens
        tokens = await token_service.create_tokens(user)
        
        # Set refresh token as HTTP-only cookie for additional security
        response.set_cookie(
            key="refresh_token",
            value=tokens["refresh_token"],
            httponly=True,
            secure=True,  # HTTPS only in production
            samesite="strict",
            max_age=30 * 24 * 60 * 60  # 30 days
        )
        
        return Token(**tokens)
        
    except AuthenticationException as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    token_request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token"""
    try:
        # Try to get refresh token from request body or cookie
        refresh_token = token_request.refresh_token
        if not refresh_token:
            refresh_token = request.cookies.get("refresh_token")
        
        if not refresh_token:
            raise AuthenticationException("Refresh token not provided")
        
        tokens = await token_service.refresh_access_token(db, refresh_token)
        if not tokens:
            raise AuthenticationException("Invalid or expired refresh token")
        
        return Token(**tokens)
        
    except AuthenticationException as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user = Depends(get_current_user)
):
    """Logout user and invalidate tokens"""
    try:
        # Get access token from Authorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header[7:]
            # Blacklist the access token
            from .service import security_service
            await security_service.blacklist_token(access_token)
        
        # Clear refresh token cookie
        response.delete_cookie("refresh_token")
        
        return {"message": "Successfully logged out"}
        
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Logout failed")


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user = Depends(get_current_user)
):
    """Get current user information"""
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update current user information"""
    try:
        updated_user = await user_service.update_user(db, current_user.id, user_update)
        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        return UserResponse.model_validate(updated_user)
        
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/change-password")
async def change_password(
    password_request: ChangePasswordRequest,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change user password"""
    try:
        success = await user_service.change_password(
            db, current_user.id, password_request.current_password, password_request.new_password
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        return {"message": "Password changed successfully"}
        
    except AuthenticationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/api-keys", response_model=APIKeyResponse)
async def create_api_key(
    api_key_create: APIKeyCreate,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new API key"""
    try:
        api_key, key = await api_key_service.create_api_key(
            db=db,
            user_id=current_user.id,
            name=api_key_create.name,
            scopes=api_key_create.scopes,
            expires_at=api_key_create.expires_at,
            rate_limit=api_key_create.rate_limit
        )
        
        # Return the key only once on creation
        result = APIKeyResponse.model_validate(api_key)
        result.key = key
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create API key")


@router.get("/api-keys", response_model=List[APIKeyList])
async def list_api_keys(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List user's API keys (without the actual keys)"""
    from sqlalchemy import select
    from .models import APIKey
    
    result = await db.execute(
        select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc())
    )
    api_keys = result.scalars().all()
    
    return [APIKeyList.model_validate(key) for key in api_keys]


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an API key"""
    from sqlalchemy import select, update
    from .models import APIKey
    
    # Check if API key belongs to current user
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id)
    )
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    
    # Deactivate the API key instead of deleting it for audit purposes
    await db.execute(
        update(APIKey).where(APIKey.id == key_id).values(is_active=False)
    )
    await db.commit()
    
    return {"message": "API key deleted successfully"}


# Admin endpoints
@router.get("/users", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """List all users (admin only)"""
    from sqlalchemy import select
    from .models import User
    
    result = await db.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    
    return [UserResponse.model_validate(user) for user in users]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID (admin only)"""
    user = await user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    return UserResponse.model_validate(user)


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Update user (admin only)"""
    try:
        updated_user = await user_service.update_user(db, user_id, user_update)
        if not updated_user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
        return UserResponse.model_validate(updated_user)
        
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))