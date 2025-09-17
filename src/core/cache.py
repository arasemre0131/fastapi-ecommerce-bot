import json
import redis.asyncio as redis
from typing import Optional, Any, Dict
from datetime import datetime, timedelta
import random
from loguru import logger

from .config import settings


class CacheService:
    def __init__(self):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)
        
        # TTL strategies with jitter
        self.TTL_OAUTH = 1800       # 30 minutes
        self.TTL_SESSION = 86400    # 24 hours  
        self.TTL_CONVERSATION = 7200  # 2 hours
        self.TTL_ORDER_CACHE = 300   # 5 minutes
        self.TTL_SHORT = 60         # 1 minute
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        try:
            value = await self.redis.get(key)
            if value:
                return json.loads(value)
            return None
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error(f"Cache get error for key {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL"""
        try:
            serialized_value = json.dumps(value, default=str)
            if ttl:
                return await self.redis.setex(key, ttl, serialized_value)
            else:
                return await self.redis.set(key, serialized_value)
        except (redis.RedisError, json.JSONEncodeError) as e:
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    async def cache_with_jitter(self, key: str, value: Any, base_ttl: int) -> bool:
        """Set value with TTL jitter to prevent thundering herd"""
        try:
            jitter = int(base_ttl * 0.1)
            ttl = base_ttl + random.randint(-jitter, jitter)
            return await self.set(key, value, ttl)
        except Exception as e:
            logger.error(f"Cache with jitter error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        try:
            return bool(await self.redis.delete(key))
        except redis.RedisError as e:
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern"""
        try:
            cursor = 0
            deleted_count = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100
                )
                if keys:
                    deleted_count += await self.redis.delete(*keys)
                if cursor == 0:
                    break
            return deleted_count
        except redis.RedisError as e:
            logger.error(f"Cache pattern invalidation error for pattern {pattern}: {e}")
            return 0
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        try:
            return bool(await self.redis.exists(key))
        except redis.RedisError as e:
            logger.error(f"Cache exists check error for key {key}: {e}")
            return False
    
    async def increment(self, key: str, amount: int = 1) -> Optional[int]:
        """Increment counter"""
        try:
            return await self.redis.incrby(key, amount)
        except redis.RedisError as e:
            logger.error(f"Cache increment error for key {key}: {e}")
            return None
    
    async def set_with_expire(self, key: str, value: Any, seconds: int) -> bool:
        """Set key with expiration time"""
        try:
            return await self.redis.setex(key, seconds, json.dumps(value, default=str))
        except (redis.RedisError, json.JSONEncodeError) as e:
            logger.error(f"Cache setex error for key {key}: {e}")
            return False
    
    async def get_or_set(self, key: str, value_func, ttl: int) -> Any:
        """Get from cache or set if not exists"""
        cached_value = await self.get(key)
        if cached_value is not None:
            return cached_value
        
        # Generate value and cache it
        value = await value_func() if callable(value_func) else value_func
        await self.cache_with_jitter(key, value, ttl)
        return value
    
    async def health_check(self) -> bool:
        """Check if Redis is healthy"""
        try:
            await self.redis.ping()
            return True
        except redis.RedisError:
            return False
    
    async def close(self):
        """Close Redis connection"""
        try:
            await self.redis.close()
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")


class SessionManager:
    """Manage user sessions, particularly for WhatsApp 24-hour window"""
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
        self.WHATSAPP_SESSION_WINDOW = 86400  # 24 hours
        self.SESSION_EXTEND_THRESHOLD = 82800  # 23 hours
    
    async def is_session_active(self, user_id: str, channel: str = "whatsapp") -> bool:
        """Check if user session is active (within 24-hour window for WhatsApp)"""
        session_key = f"session:{channel}:{user_id}"
        session_data = await self.cache.get(session_key)
        
        if not session_data:
            return False
        
        last_message_time = datetime.fromisoformat(session_data["last_message"])
        time_diff = datetime.now() - last_message_time
        
        if channel == "whatsapp":
            return time_diff.total_seconds() < self.WHATSAPP_SESSION_WINDOW
        else:
            return time_diff.total_seconds() < 3600  # 1 hour for other channels
    
    async def update_session(self, user_id: str, channel: str = "whatsapp") -> bool:
        """Update session timestamp"""
        session_key = f"session:{channel}:{user_id}"
        session_data = {
            "user_id": user_id,
            "channel": channel,
            "last_message": datetime.now().isoformat(),
            "message_count": 1
        }
        
        # Get existing session to increment message count
        existing_session = await self.cache.get(session_key)
        if existing_session:
            session_data["message_count"] = existing_session.get("message_count", 0) + 1
        
        ttl = self.WHATSAPP_SESSION_WINDOW if channel == "whatsapp" else 3600
        return await self.cache.set_with_expire(session_key, session_data, ttl)
    
    async def extend_session(self, user_id: str, channel: str = "whatsapp") -> bool:
        """Extend session if close to expiry"""
        session_key = f"session:{channel}:{user_id}"
        session_data = await self.cache.get(session_key)
        
        if not session_data:
            return False
        
        last_message_time = datetime.fromisoformat(session_data["last_message"])
        time_diff = datetime.now() - last_message_time
        
        # Extend if within threshold
        if time_diff.total_seconds() > self.SESSION_EXTEND_THRESHOLD:
            return await self.update_session(user_id, channel)
        
        return True
    
    async def end_session(self, user_id: str, channel: str = "whatsapp") -> bool:
        """End user session"""
        session_key = f"session:{channel}:{user_id}"
        return await self.cache.delete(session_key)
    
    async def get_session_info(self, user_id: str, channel: str = "whatsapp") -> Optional[Dict]:
        """Get session information"""
        session_key = f"session:{channel}:{user_id}"
        return await self.cache.get(session_key)


class ConversationCache:
    """Cache conversation context and state"""
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
    
    async def get_conversation_context(self, conversation_id: int) -> Optional[Dict]:
        """Get conversation context from cache"""
        key = f"conversation:context:{conversation_id}"
        return await self.cache.get(key)
    
    async def set_conversation_context(self, conversation_id: int, context: Dict) -> bool:
        """Cache conversation context"""
        key = f"conversation:context:{conversation_id}"
        return await self.cache.cache_with_jitter(key, context, self.cache.TTL_CONVERSATION)
    
    async def get_user_conversations(self, user_id: str) -> Optional[Dict]:
        """Get user's active conversations"""
        key = f"user:conversations:{user_id}"
        return await self.cache.get(key)
    
    async def add_user_conversation(self, user_id: str, conversation_id: int) -> bool:
        """Add conversation to user's active list"""
        key = f"user:conversations:{user_id}"
        conversations = await self.cache.get(key) or {"active": [], "recent": []}
        
        if conversation_id not in conversations["active"]:
            conversations["active"].append(conversation_id)
        
        return await self.cache.cache_with_jitter(key, conversations, self.cache.TTL_CONVERSATION)
    
    async def remove_user_conversation(self, user_id: str, conversation_id: int) -> bool:
        """Remove conversation from user's active list"""
        key = f"user:conversations:{user_id}"
        conversations = await self.cache.get(key)
        
        if not conversations:
            return True
        
        if conversation_id in conversations["active"]:
            conversations["active"].remove(conversation_id)
            conversations["recent"].append(conversation_id)
            
            # Keep only last 10 recent conversations
            conversations["recent"] = conversations["recent"][-10:]
        
        return await self.cache.set(key, conversations, self.cache.TTL_CONVERSATION)


class RateLimitCache:
    """Rate limiting using Redis"""
    
    def __init__(self, cache_service: CacheService):
        self.cache = cache_service
    
    async def is_rate_limited(self, identifier: str, limit: int, window: int) -> bool:
        """Check if identifier is rate limited"""
        key = f"rate_limit:{identifier}"
        current_count = await self.cache.get(key) or 0
        return current_count >= limit
    
    async def increment_rate_limit(self, identifier: str, window: int) -> int:
        """Increment rate limit counter"""
        key = f"rate_limit:{identifier}"
        
        # Use Redis pipeline for atomic operations
        async with self.cache.redis.pipeline() as pipe:
            await pipe.incr(key)
            await pipe.expire(key, window)
            results = await pipe.execute()
            return results[0]
    
    async def get_rate_limit_info(self, identifier: str) -> Dict:
        """Get current rate limit status"""
        key = f"rate_limit:{identifier}"
        count = await self.cache.get(key) or 0
        ttl = await self.cache.redis.ttl(key)
        
        return {
            "current_count": count,
            "ttl": ttl,
            "reset_time": datetime.now() + timedelta(seconds=ttl) if ttl > 0 else None
        }


# Global cache instances
cache_service = CacheService()
session_manager = SessionManager(cache_service)
conversation_cache = ConversationCache(cache_service)
rate_limit_cache = RateLimitCache(cache_service)