import openai
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger

from ...core.config import settings
from ...core.exceptions import OpenAIAPIException
from ...core.cache import cache_service


# Configure OpenAI client
openai.api_key = settings.openai_api_key


class OpenAIService:
    def __init__(self):
        self.model = settings.openai_model
        self.max_tokens = settings.openai_max_tokens
        self.temperature = settings.openai_temperature
        
        # Function definitions for e-commerce support
        self.functions = [
            {
                "name": "check_order_status",
                "description": "Check order status and tracking information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {
                            "type": "string",
                            "description": "Order number or ID"
                        },
                        "customer_email": {
                            "type": "string",
                            "description": "Customer email for verification"
                        }
                    },
                    "required": ["order_number"]
                }
            },
            {
                "name": "process_return_request",
                "description": "Process return or refund request",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_number": {"type": "string"},
                        "reason": {"type": "string"},
                        "items": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["order_number", "reason"]
                }
            },
            {
                "name": "search_products",
                "description": "Search for products in the store",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "category": {"type": "string"},
                        "max_price": {"type": "number"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "update_customer_info",
                "description": "Update customer information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                        "field": {"type": "string"},
                        "new_value": {"type": "string"}
                    },
                    "required": ["customer_id", "field", "new_value"]
                }
            }
        ]
    
    def count_tokens(self, messages: List[Dict]) -> int:
        """Estimate token count for messages"""
        # Simple estimation - in production use tiktoken
        total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
        return total_chars // 4  # Rough estimate: 1 token ≈ 4 characters
    
    def manage_conversation_context(self, messages: List[Dict], max_tokens: int = 7000) -> List[Dict]:
        """Manage conversation context to stay within token limits"""
        if not messages:
            return messages
        
        current_tokens = self.count_tokens(messages)
        
        while current_tokens > max_tokens and len(messages) > 2:
            # Keep system message and remove oldest non-system messages
            for i in range(1, len(messages)):
                if messages[i]["role"] != "system":
                    messages.pop(i)
                    break
            current_tokens = self.count_tokens(messages)
        
        return messages
    
    async def generate_response(
        self,
        message: str,
        conversation_context: Dict,
        conversation_id: int,
        merchant_context: Dict = None
    ) -> str:
        """Generate AI response with function calling support"""
        try:
            # Build conversation messages
            messages = self._build_conversation_messages(message, conversation_context, merchant_context)
            
            # Manage context length
            messages = self.manage_conversation_context(messages)
            
            # Make OpenAI API call
            response = await openai.ChatCompletion.acreate(
                model=self.model,
                messages=messages,
                functions=self.functions,
                function_call="auto",
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=30
            )
            
            message_obj = response.choices[0].message
            
            # Check if AI wants to call a function
            if message_obj.get("function_call"):
                function_response = await self._execute_function(
                    message_obj.function_call,
                    conversation_context,
                    merchant_context
                )
                
                # Add function call and response to conversation
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "function_call": message_obj.function_call
                })
                messages.append({
                    "role": "function",
                    "name": message_obj.function_call.name,
                    "content": json.dumps(function_response)
                })
                
                # Generate final response with function result
                final_response = await openai.ChatCompletion.acreate(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )
                
                return final_response.choices[0].message.content
            
            return message_obj.content
            
        except openai.error.RateLimitError:
            logger.error("OpenAI rate limit exceeded")
            return "I'm experiencing high demand right now. Please try again in a moment."
        
        except openai.error.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return "I'm having trouble processing your request right now. Please try again later."
        
        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
            return "I apologize, but I'm having technical difficulties. Please try again or contact support."
    
    def _build_conversation_messages(
        self,
        message: str,
        conversation_context: Dict,
        merchant_context: Dict = None
    ) -> List[Dict]:
        """Build conversation messages for OpenAI"""
        
        # System message with context
        system_prompt = self._build_system_prompt(merchant_context)
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add conversation history
        conversation_history = conversation_context.get("messages", [])
        for msg in conversation_history[-10:]:  # Last 10 messages
            messages.append({
                "role": "user" if msg.get("sender_type") == "customer" else "assistant",
                "content": msg.get("content", "")
            })
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        return messages
    
    def _build_system_prompt(self, merchant_context: Dict = None) -> str:
        """Build system prompt with merchant context"""
        base_prompt = """
You are a helpful e-commerce customer support assistant. Your role is to:

1. Help customers with order inquiries, tracking, and status updates
2. Assist with product searches and recommendations  
3. Process return and refund requests
4. Update customer information when needed
5. Provide general store information and policies

Guidelines:
- Be friendly, professional, and helpful
- Always verify customer identity for sensitive operations
- Use available functions to get real-time information
- If you cannot help with something, offer to connect them with a human agent
- Keep responses concise but informative
"""
        
        if merchant_context:
            store_name = merchant_context.get("name", "our store")
            base_prompt += f"\n\nYou are assisting customers of {store_name}."
            
            if merchant_context.get("policies"):
                base_prompt += f"\n\nStore policies: {merchant_context['policies']}"
        
        return base_prompt
    
    async def _execute_function(
        self,
        function_call: Dict,
        conversation_context: Dict,
        merchant_context: Dict = None
    ) -> Dict[str, Any]:
        """Execute function called by AI"""
        function_name = function_call.name
        arguments = json.loads(function_call.arguments)
        
        try:
            if function_name == "check_order_status":
                return await self._check_order_status(arguments, merchant_context)
            elif function_name == "process_return_request":
                return await self._process_return_request(arguments, merchant_context)
            elif function_name == "search_products":
                return await self._search_products(arguments, merchant_context)
            elif function_name == "update_customer_info":
                return await self._update_customer_info(arguments, merchant_context)
            else:
                return {"error": f"Unknown function: {function_name}"}
                
        except Exception as e:
            logger.error(f"Error executing function {function_name}: {e}")
            return {"error": f"Failed to execute {function_name}"}
    
    async def _check_order_status(self, args: Dict, merchant_context: Dict) -> Dict:
        """Check order status function"""
        order_number = args.get("order_number")
        customer_email = args.get("customer_email")
        
        # Get merchant ID from context
        merchant_id = merchant_context.get("id") if merchant_context else None
        if not merchant_id:
            return {"error": "Merchant context not available"}
        
        try:
            from ...core.database import AsyncSessionLocal
            from ...core.models import Order
            from sqlalchemy import select
            
            async with AsyncSessionLocal() as db:
                # Search for order
                query = select(Order).where(
                    Order.merchant_id == merchant_id,
                    Order.order_number == order_number
                )
                
                if customer_email:
                    query = query.where(Order.customer_email == customer_email)
                
                result = await db.execute(query)
                order = result.scalar_one_or_none()
                
                if not order:
                    return {
                        "found": False,
                        "message": "Order not found. Please check the order number and email."
                    }
                
                return {
                    "found": True,
                    "order_number": order.order_number,
                    "status": order.status,
                    "financial_status": order.financial_status,
                    "fulfillment_status": order.fulfillment_status,
                    "total_amount": order.total_amount,
                    "currency": order.currency,
                    "tracking_number": order.tracking_number,
                    "tracking_url": order.tracking_url,
                    "order_date": order.order_date.isoformat() if order.order_date else None
                }
                
        except Exception as e:
            logger.error(f"Error checking order status: {e}")
            return {"error": "Unable to check order status at this time"}
    
    async def _process_return_request(self, args: Dict, merchant_context: Dict) -> Dict:
        """Process return request function"""
        order_number = args.get("order_number")
        reason = args.get("reason")
        items = args.get("items", [])
        
        # In a real implementation, this would create a return request in the system
        return {
            "success": True,
            "return_id": f"RET-{order_number}-{datetime.now().strftime('%Y%m%d')}",
            "message": f"Return request created for order {order_number}. You will receive an email with return instructions.",
            "next_steps": "Check your email for return shipping label and instructions."
        }
    
    async def _search_products(self, args: Dict, merchant_context: Dict) -> Dict:
        """Search products function"""
        query = args.get("query")
        category = args.get("category")
        max_price = args.get("max_price")
        
        merchant_id = merchant_context.get("id") if merchant_context else None
        if not merchant_id:
            return {"error": "Merchant context not available"}
        
        # This would integrate with the actual product search
        # For now, return a mock response
        return {
            "found": True,
            "products": [
                {
                    "id": "123",
                    "name": f"Product matching '{query}'",
                    "price": 29.99,
                    "description": "Great product that matches your search",
                    "in_stock": True
                }
            ],
            "total_found": 1
        }
    
    async def _update_customer_info(self, args: Dict, merchant_context: Dict) -> Dict:
        """Update customer information function"""
        customer_id = args.get("customer_id")
        field = args.get("field")
        new_value = args.get("new_value")
        
        # This would update customer information in the database
        # For now, return a success response
        return {
            "success": True,
            "message": f"Updated {field} for customer {customer_id}",
            "field": field,
            "new_value": new_value
        }


# Global OpenAI service instance
openai_service = OpenAIService()


async def generate_response(
    message: str,
    conversation_context: Dict,
    conversation_id: int,
    merchant_context: Dict = None
) -> str:
    """Main function to generate AI response"""
    return await openai_service.generate_response(
        message, conversation_context, conversation_id, merchant_context
    )