import asyncio
import json
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import redis.asyncio as redis
from loguru import logger
from dataclasses import dataclass

from .config import settings


class QueuePriority(Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class QueueTask:
    id: str
    queue_name: str
    task_type: str
    payload: Dict[str, Any]
    priority: QueuePriority = QueuePriority.NORMAL
    max_retries: int = 3
    retry_count: int = 0
    delay_seconds: int = 0
    created_at: datetime = None
    scheduled_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.scheduled_at is None:
            self.scheduled_at = self.created_at + timedelta(seconds=self.delay_seconds)


class AsyncQueue:
    """Redis-based async queue with retry logic and priority support"""
    
    def __init__(self, redis_url: str = None):
        self.redis_url = redis_url or settings.redis_queue_url
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        self.task_processors: Dict[str, Callable] = {}
        self.running = False
        
        # Queue configuration
        self.QUEUE_PREFIX = "queue"
        self.PROCESSING_PREFIX = "processing"
        self.FAILED_PREFIX = "failed"
        self.SCHEDULED_PREFIX = "scheduled"
        
        # Priority weights for queue processing order
        self.PRIORITY_WEIGHTS = {
            QueuePriority.CRITICAL: 100,
            QueuePriority.HIGH: 75,
            QueuePriority.NORMAL: 50,
            QueuePriority.LOW: 25
        }
    
    def register_processor(self, task_type: str, processor: Callable):
        """Register a task processor function"""
        self.task_processors[task_type] = processor
        logger.info(f"Registered processor for task type: {task_type}")
    
    async def enqueue(self, task: QueueTask) -> bool:
        """Add task to queue"""
        try:
            task_data = {
                "id": task.id,
                "queue_name": task.queue_name,
                "task_type": task.task_type,
                "payload": task.payload,
                "priority": task.priority.value,
                "max_retries": task.max_retries,
                "retry_count": task.retry_count,
                "created_at": task.created_at.isoformat(),
                "scheduled_at": task.scheduled_at.isoformat()
            }
            
            if task.delay_seconds > 0:
                # Schedule task for later processing
                scheduled_key = f"{self.SCHEDULED_PREFIX}:{task.queue_name}"
                score = task.scheduled_at.timestamp()
                await self.redis.zadd(scheduled_key, {json.dumps(task_data): score})
            else:
                # Add to immediate processing queue
                queue_key = f"{self.QUEUE_PREFIX}:{task.queue_name}:{task.priority.value}"
                await self.redis.lpush(queue_key, json.dumps(task_data))
            
            logger.info(f"Enqueued task {task.id} to {task.queue_name} with priority {task.priority.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue task {task.id}: {e}")
            return False
    
    async def dequeue(self, queue_name: str, timeout: int = 10) -> Optional[QueueTask]:
        """Get next task from queue (priority-based)"""
        try:
            # Check scheduled tasks first
            await self._process_scheduled_tasks(queue_name)
            
            # Try to get task from priority queues (highest to lowest)
            for priority in [QueuePriority.CRITICAL, QueuePriority.HIGH, QueuePriority.NORMAL, QueuePriority.LOW]:
                queue_key = f"{self.QUEUE_PREFIX}:{queue_name}:{priority.value}"
                
                # Use blocking pop with timeout
                result = await self.redis.brpop(queue_key, timeout=timeout)
                if result:
                    _, task_data = result
                    task_dict = json.loads(task_data)
                    
                    # Move to processing set
                    processing_key = f"{self.PROCESSING_PREFIX}:{queue_name}"
                    await self.redis.sadd(processing_key, task_data)
                    
                    return self._dict_to_task(task_dict)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to dequeue from {queue_name}: {e}")
            return None
    
    async def _process_scheduled_tasks(self, queue_name: str):
        """Move scheduled tasks to immediate queue when ready"""
        try:
            scheduled_key = f"{self.SCHEDULED_PREFIX}:{queue_name}"
            now = datetime.utcnow().timestamp()
            
            # Get tasks ready for processing
            ready_tasks = await self.redis.zrangebyscore(scheduled_key, 0, now, withscores=True)
            
            for task_data, score in ready_tasks:
                # Remove from scheduled and add to immediate queue
                await self.redis.zrem(scheduled_key, task_data)
                
                task_dict = json.loads(task_data)
                priority = QueuePriority(task_dict["priority"])
                queue_key = f"{self.QUEUE_PREFIX}:{queue_name}:{priority.value}"
                
                await self.redis.lpush(queue_key, task_data)
                
        except Exception as e:
            logger.error(f"Failed to process scheduled tasks for {queue_name}: {e}")
    
    async def complete_task(self, task: QueueTask) -> bool:
        """Mark task as completed"""
        try:
            processing_key = f"{self.PROCESSING_PREFIX}:{task.queue_name}"
            task_data = json.dumps(self._task_to_dict(task))
            
            # Remove from processing set
            await self.redis.srem(processing_key, task_data)
            
            logger.info(f"Completed task {task.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete task {task.id}: {e}")
            return False
    
    async def fail_task(self, task: QueueTask, error_message: str = None) -> bool:
        """Handle task failure with retry logic"""
        try:
            processing_key = f"{self.PROCESSING_PREFIX}:{task.queue_name}"
            task_data = json.dumps(self._task_to_dict(task))
            
            # Remove from processing
            await self.redis.srem(processing_key, task_data)
            
            if task.retry_count < task.max_retries:
                # Retry with exponential backoff
                task.retry_count += 1
                task.delay_seconds = min(2 ** task.retry_count * 60, 3600)  # Max 1 hour delay
                task.scheduled_at = datetime.utcnow() + timedelta(seconds=task.delay_seconds)
                
                logger.warning(f"Retrying task {task.id} (attempt {task.retry_count}/{task.max_retries})")
                return await self.enqueue(task)
            else:
                # Max retries reached, move to failed queue
                failed_key = f"{self.FAILED_PREFIX}:{task.queue_name}"
                failed_data = self._task_to_dict(task)
                failed_data["error_message"] = error_message
                failed_data["failed_at"] = datetime.utcnow().isoformat()
                
                await self.redis.lpush(failed_key, json.dumps(failed_data))
                
                logger.error(f"Task {task.id} failed permanently after {task.max_retries} retries")
                return False
                
        except Exception as e:
            logger.error(f"Failed to handle task failure for {task.id}: {e}")
            return False
    
    async def start_worker(self, queue_name: str):
        """Start processing tasks from queue"""
        self.running = True
        logger.info(f"Starting queue worker for {queue_name}")
        
        while self.running:
            try:
                task = await self.dequeue(queue_name, timeout=5)
                if task:
                    await self._process_task(task)
                    
            except Exception as e:
                logger.error(f"Worker error for {queue_name}: {e}")
                await asyncio.sleep(1)
    
    async def stop_worker(self):
        """Stop queue worker"""
        self.running = False
        logger.info("Stopping queue worker")
    
    async def _process_task(self, task: QueueTask):
        """Process individual task"""
        try:
            processor = self.task_processors.get(task.task_type)
            if not processor:
                logger.error(f"No processor registered for task type: {task.task_type}")
                await self.fail_task(task, f"No processor for task type: {task.task_type}")
                return
            
            logger.info(f"Processing task {task.id} of type {task.task_type}")
            
            # Execute task processor
            result = await processor(task.payload)
            
            # Mark as completed
            await self.complete_task(task)
            
            logger.info(f"Successfully processed task {task.id}")
            
        except Exception as e:
            logger.error(f"Task processing failed for {task.id}: {e}")
            await self.fail_task(task, str(e))
    
    def _task_to_dict(self, task: QueueTask) -> Dict:
        """Convert QueueTask to dictionary"""
        return {
            "id": task.id,
            "queue_name": task.queue_name,
            "task_type": task.task_type,
            "payload": task.payload,
            "priority": task.priority.value,
            "max_retries": task.max_retries,
            "retry_count": task.retry_count,
            "created_at": task.created_at.isoformat(),
            "scheduled_at": task.scheduled_at.isoformat()
        }
    
    def _dict_to_task(self, task_dict: Dict) -> QueueTask:
        """Convert dictionary to QueueTask"""
        return QueueTask(
            id=task_dict["id"],
            queue_name=task_dict["queue_name"],
            task_type=task_dict["task_type"],
            payload=task_dict["payload"],
            priority=QueuePriority(task_dict["priority"]),
            max_retries=task_dict["max_retries"],
            retry_count=task_dict["retry_count"],
            created_at=datetime.fromisoformat(task_dict["created_at"]),
            scheduled_at=datetime.fromisoformat(task_dict["scheduled_at"])
        )
    
    async def get_queue_stats(self, queue_name: str) -> Dict:
        """Get queue statistics"""
        try:
            stats = {"queue_name": queue_name}
            
            # Count tasks in each priority queue
            for priority in QueuePriority:
                queue_key = f"{self.QUEUE_PREFIX}:{queue_name}:{priority.value}"
                stats[f"{priority.value}_count"] = await self.redis.llen(queue_key)
            
            # Count scheduled tasks
            scheduled_key = f"{self.SCHEDULED_PREFIX}:{queue_name}"
            stats["scheduled_count"] = await self.redis.zcard(scheduled_key)
            
            # Count processing tasks
            processing_key = f"{self.PROCESSING_PREFIX}:{queue_name}"
            stats["processing_count"] = await self.redis.scard(processing_key)
            
            # Count failed tasks
            failed_key = f"{self.FAILED_PREFIX}:{queue_name}"
            stats["failed_count"] = await self.redis.llen(failed_key)
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get queue stats for {queue_name}: {e}")
            return {}
    
    async def health_check(self) -> bool:
        """Check if queue system is healthy"""
        try:
            await self.redis.ping()
            return True
        except Exception:
            return False
    
    async def close(self):
        """Close Redis connection"""
        try:
            await self.redis.close()
        except Exception as e:
            logger.error(f"Error closing queue Redis connection: {e}")


# Global queue instance
async_queue = AsyncQueue()


# Task processors
async def process_webhook_task(payload: Dict[str, Any]) -> Dict:
    """Process webhook events"""
    try:
        webhook_type = payload.get("type")
        merchant_id = payload.get("merchant_id")
        data = payload.get("data")
        
        logger.info(f"Processing webhook: {webhook_type} for merchant {merchant_id}")
        
        # Route to appropriate handler based on webhook type
        if webhook_type == "shopify.order.created":
            from ..integrations.shopify.webhooks import handle_order_created
            return await handle_order_created(data, merchant_id)
        elif webhook_type == "whatsapp.message.received":
            from ..integrations.whatsapp.handlers import handle_incoming_message
            return await handle_incoming_message(data, merchant_id)
        else:
            logger.warning(f"Unknown webhook type: {webhook_type}")
            return {"status": "ignored", "reason": "unknown_webhook_type"}
            
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        raise


async def process_ai_response_task(payload: Dict[str, Any]) -> Dict:
    """Process AI response generation"""
    try:
        conversation_id = payload.get("conversation_id")
        message = payload.get("message")
        context = payload.get("context", {})
        
        logger.info(f"Processing AI response for conversation {conversation_id}")
        
        from ..integrations.openai.chat import generate_response
        response = await generate_response(message, context, conversation_id)
        
        return {"response": response, "conversation_id": conversation_id}
        
    except Exception as e:
        logger.error(f"AI response generation failed: {e}")
        raise


# Register task processors
async_queue.register_processor("webhook.process", process_webhook_task)
async_queue.register_processor("ai.generate_response", process_ai_response_task)