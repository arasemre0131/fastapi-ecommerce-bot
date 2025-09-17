from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List

from .models import User
from .service import security_service, user_service, api_key_service
from .schemas import TokenData
from ..core.database import get_db
from ..core.exceptions import AuthenticationException


security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token"""
    try:
        # Extract token
        token = credentials.credentials
        
        # Check if token is blacklisted
        if await security_service.is_token_blacklisted(token):
            raise AuthenticationException("Token has been revoked")
        
        # Verify token
        token_data = security_service.verify_token(token, "access")
        if token_data is None:
            raise AuthenticationException("Could not validate credentials")
        
        # Get user from database
        user = await user_service.get_user_by_id(db, token_data.user_id)
        if user is None:
            raise AuthenticationException("User not found")
        
        if not user.is_active:
            raise AuthenticationException("User account is inactive")
        
        return user
        
    except AuthenticationException:
        raise
    except Exception as e:
        raise AuthenticationException("Could not validate credentials")


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current active user"""
    if not current_user.is_active:
        raise AuthenticationException("User account is inactive")
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current superuser"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user


async def get_user_from_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Get user from API key authentication"""
    # Check for API key in headers
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        return None
    
    # Verify API key
    result = await api_key_service.verify_api_key(db, api_key)
    if not result:
        return None
    
    user, api_key_obj = result
    
    # Store API key info in request state for rate limiting
    request.state.api_key = api_key_obj
    
    return user


async def get_current_user_or_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> User:
    """Get user from either JWT token or API key"""
    # Try API key first
    user = await get_user_from_api_key(request, db)
    if user:
        return user
    
    # Fall back to JWT token
    if credentials:
        token = credentials.credentials
        
        # Check if token is blacklisted
        if await security_service.is_token_blacklisted(token):
            raise AuthenticationException("Token has been revoked")
        
        # Verify token
        token_data = security_service.verify_token(token, "access")
        if token_data is None:
            raise AuthenticationException("Could not validate credentials")
        
        # Get user from database
        user = await user_service.get_user_by_id(db, token_data.user_id)
        if user is None:
            raise AuthenticationException("User not found")
        
        if not user.is_active:
            raise AuthenticationException("User account is inactive")
        
        return user
    
    raise AuthenticationException("No valid authentication provided")


def require_scopes(scopes: List[str]):
    """Dependency to require specific scopes"""
    def scope_checker(
        current_user: User = Depends(get_current_user_or_api_key),
        request: Request = None
    ):
        # If using API key, check scopes
        if hasattr(request.state, 'api_key'):
            api_key = request.state.api_key
            api_key_scopes = api_key.scopes.split(",") if api_key.scopes else []
            
            for scope in scopes:
                if scope not in api_key_scopes:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Not enough permissions. Required scope: {scope}"
                    )
        
        # For JWT tokens, scopes are embedded in the token (would need to extract them)
        # For now, we'll assume JWT tokens have all scopes
        
        return current_user
    
    return scope_checker


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[User]:
    """Get user if authenticated, but don't require authentication"""
    try:
        return await get_current_user_or_api_key(request, db, credentials)
    except:
        return None


# Rate limiting dependency for API keys
async def check_api_key_rate_limit(
    request: Request,
    current_user: User = Depends(get_current_user_or_api_key)
):
    """Check rate limit for API key usage"""
    if not hasattr(request.state, 'api_key'):
        return  # No rate limiting for JWT tokens
    
    api_key = request.state.api_key
    if not api_key.rate_limit:
        return  # No rate limit set
    
    from ..core.cache import rate_limit_cache
    
    # Check current usage
    identifier = f"api_key:{api_key.id}"
    is_limited = await rate_limit_cache.is_rate_limited(
        identifier, 
        api_key.rate_limit, 
        3600  # 1 hour window
    )
    
    if is_limited:
        rate_info = await rate_limit_cache.get_rate_limit_info(identifier)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API key rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(api_key.rate_limit),
                "X-RateLimit-Remaining": str(max(0, api_key.rate_limit - rate_info["current_count"])),
                "X-RateLimit-Reset": str(rate_info["reset_time"].isoformat() if rate_info["reset_time"] else "")
            }
        )
    
    # Increment usage
    await rate_limit_cache.increment_rate_limit(identifier, 3600)