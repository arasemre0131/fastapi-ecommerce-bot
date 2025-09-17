import secrets
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from loguru import logger

from .models import User, RefreshToken, APIKey
from .schemas import UserCreate, UserUpdate, TokenData
from ..core.config import settings
from ..core.exceptions import AuthenticationException, ValidationException
from ..core.cache import cache_service


class SecurityService:
    def __init__(self):
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        self.algorithm = settings.algorithm
        self.secret_key = settings.secret_key
        self.access_token_expire_minutes = settings.access_token_expire_minutes
        
        # Account lockout settings
        self.max_failed_attempts = 5
        self.lockout_duration = timedelta(minutes=30)
    
    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt"""
        return self.pwd_context.hash(password)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return self.pwd_context.verify(plain_password, hashed_password)
    
    def generate_api_key(self) -> tuple[str, str]:
        """Generate API key and its hash"""
        # Generate a secure random key
        key = f"eck_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return key, key_hash
    
    def create_access_token(self, data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """Create JWT access token"""
        to_encode = data.copy()
        
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        
        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt
    
    def create_refresh_token(self, user_id: int) -> str:
        """Create refresh token"""
        data = {
            "user_id": user_id,
            "type": "refresh",
            "exp": datetime.utcnow() + timedelta(days=30)  # 30 days
        }
        return jwt.encode(data, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str, token_type: str = "access") -> Optional[TokenData]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            if payload.get("type") != token_type:
                return None
            
            user_id: int = payload.get("user_id")
            if user_id is None:
                return None
            
            scopes: list[str] = payload.get("scopes", [])
            return TokenData(user_id=user_id, scopes=scopes)
            
        except JWTError:
            return None
    
    async def is_token_blacklisted(self, token: str) -> bool:
        """Check if token is blacklisted"""
        return await cache_service.exists(f"blacklist:token:{token}")
    
    async def blacklist_token(self, token: str, expires_in: int = None):
        """Add token to blacklist"""
        if expires_in is None:
            expires_in = self.access_token_expire_minutes * 60
        
        await cache_service.set_with_expire(f"blacklist:token:{token}", True, expires_in)


class UserService:
    def __init__(self, security_service: SecurityService):
        self.security = security_service
    
    async def create_user(self, db: AsyncSession, user_create: UserCreate) -> User:
        """Create a new user"""
        # Check if user already exists
        existing_user = await self.get_user_by_email(db, user_create.email)
        if existing_user:
            raise ValidationException("User with this email already exists")
        
        if user_create.username:
            existing_username = await self.get_user_by_username(db, user_create.username)
            if existing_username:
                raise ValidationException("User with this username already exists")
        
        # Create user
        hashed_password = self.security.hash_password(user_create.password)
        
        db_user = User(
            email=user_create.email,
            username=user_create.username,
            full_name=user_create.full_name,
            hashed_password=hashed_password,
            is_active=user_create.is_active
        )
        
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        
        logger.info(f"Created new user: {user_create.email}")
        return db_user
    
    async def authenticate_user(self, db: AsyncSession, email: str, password: str, ip_address: str = None) -> Optional[User]:
        """Authenticate user with email and password"""
        user = await self.get_user_by_email(db, email)
        if not user:
            return None
        
        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            logger.warning(f"Login attempt for locked account: {email}")
            raise AuthenticationException("Account is temporarily locked due to multiple failed login attempts")
        
        # Verify password
        if not self.security.verify_password(password, user.hashed_password):
            await self._handle_failed_login(db, user, ip_address)
            return None
        
        # Reset failed attempts on successful login
        if user.failed_login_attempts > 0:
            await self._reset_failed_attempts(db, user)
        
        # Update last login
        user.last_login = datetime.utcnow()
        await db.commit()
        
        logger.info(f"User authenticated successfully: {email}")
        return user
    
    async def get_user_by_id(self, db: AsyncSession, user_id: int) -> Optional[User]:
        """Get user by ID"""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
    
    async def get_user_by_email(self, db: AsyncSession, email: str) -> Optional[User]:
        """Get user by email"""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
    
    async def get_user_by_username(self, db: AsyncSession, username: str) -> Optional[User]:
        """Get user by username"""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()
    
    async def update_user(self, db: AsyncSession, user_id: int, user_update: UserUpdate) -> Optional[User]:
        """Update user information"""
        user = await self.get_user_by_id(db, user_id)
        if not user:
            return None
        
        update_data = user_update.model_dump(exclude_unset=True)
        
        # Check for email conflicts
        if "email" in update_data and update_data["email"] != user.email:
            existing_user = await self.get_user_by_email(db, update_data["email"])
            if existing_user:
                raise ValidationException("User with this email already exists")
        
        # Check for username conflicts
        if "username" in update_data and update_data["username"] != user.username:
            existing_user = await self.get_user_by_username(db, update_data["username"])
            if existing_user:
                raise ValidationException("User with this username already exists")
        
        for field, value in update_data.items():
            setattr(user, field, value)
        
        await db.commit()
        await db.refresh(user)
        
        logger.info(f"Updated user: {user.email}")
        return user
    
    async def change_password(self, db: AsyncSession, user_id: int, current_password: str, new_password: str) -> bool:
        """Change user password"""
        user = await self.get_user_by_id(db, user_id)
        if not user:
            return False
        
        # Verify current password
        if not self.security.verify_password(current_password, user.hashed_password):
            raise AuthenticationException("Current password is incorrect")
        
        # Update password
        user.hashed_password = self.security.hash_password(new_password)
        await db.commit()
        
        logger.info(f"Password changed for user: {user.email}")
        return True
    
    async def _handle_failed_login(self, db: AsyncSession, user: User, ip_address: str = None):
        """Handle failed login attempt"""
        user.failed_login_attempts += 1
        
        if user.failed_login_attempts >= self.security.max_failed_attempts:
            user.locked_until = datetime.utcnow() + self.security.lockout_duration
            logger.warning(f"Account locked due to failed attempts: {user.email} from IP: {ip_address}")
        
        await db.commit()
    
    async def _reset_failed_attempts(self, db: AsyncSession, user: User):
        """Reset failed login attempts"""
        user.failed_login_attempts = 0
        user.locked_until = None
        await db.commit()


class TokenService:
    def __init__(self, security_service: SecurityService):
        self.security = security_service
    
    async def create_tokens(self, user: User) -> Dict[str, Any]:
        """Create access and refresh tokens for user"""
        # Create access token
        access_token_data = {
            "user_id": user.id,
            "email": user.email,
            "scopes": ["user"]  # Default scopes
        }
        
        access_token = self.security.create_access_token(access_token_data)
        refresh_token = self.security.create_refresh_token(user.id)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.security.access_token_expire_minutes * 60
        }
    
    async def refresh_access_token(self, db: AsyncSession, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Create new access token using refresh token"""
        # Verify refresh token
        token_data = self.security.verify_token(refresh_token, "refresh")
        if not token_data:
            return None
        
        # Check if refresh token exists in database and is not revoked
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token == refresh_token,
                RefreshToken.is_revoked == False,
                RefreshToken.expires_at > datetime.utcnow()
            )
        )
        db_token = result.scalar_one_or_none()
        if not db_token:
            return None
        
        # Get user
        user_service = UserService(self.security)
        user = await user_service.get_user_by_id(db, token_data.user_id)
        if not user or not user.is_active:
            return None
        
        # Create new tokens
        return await self.create_tokens(user)
    
    async def revoke_refresh_token(self, db: AsyncSession, token: str) -> bool:
        """Revoke refresh token"""
        result = await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token == token)
            .values(is_revoked=True)
        )
        await db.commit()
        return result.rowcount > 0


class APIKeyService:
    def __init__(self, security_service: SecurityService):
        self.security = security_service
    
    async def create_api_key(self, db: AsyncSession, user_id: int, name: str, scopes: list[str] = None, expires_at: datetime = None, rate_limit: int = None) -> tuple[APIKey, str]:
        """Create new API key"""
        key, key_hash = self.security.generate_api_key()
        
        api_key = APIKey(
            user_id=user_id,
            key_name=name,
            key_hash=key_hash,
            scopes=",".join(scopes or []),
            expires_at=expires_at,
            rate_limit=rate_limit
        )
        
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)
        
        logger.info(f"Created API key '{name}' for user {user_id}")
        return api_key, key
    
    async def verify_api_key(self, db: AsyncSession, key: str) -> Optional[tuple[User, APIKey]]:
        """Verify API key and return user and key info"""
        if not key.startswith("eck_"):
            return None
        
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        
        result = await db.execute(
            select(APIKey, User)
            .join(User, APIKey.user_id == User.id)
            .where(
                APIKey.key_hash == key_hash,
                APIKey.is_active == True,
                User.is_active == True
            )
        )
        
        row = result.first()
        if not row:
            return None
        
        api_key, user = row
        
        # Check expiration
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None
        
        # Update usage statistics
        api_key.last_used = datetime.utcnow()
        api_key.usage_count += 1
        await db.commit()
        
        return user, api_key


# Global service instances
security_service = SecurityService()
user_service = UserService(security_service)
token_service = TokenService(security_service)
api_key_service = APIKeyService(security_service)