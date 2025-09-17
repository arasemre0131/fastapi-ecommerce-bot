import base64
import hmac
import hashlib
import json
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import Request, HTTPException
from loguru import logger

from ...core.config import settings
from ...core.exceptions import ShopifyAPIException
from ...core.queue import async_queue, QueueTask, QueuePriority


def verify_webhook_signature(data: bytes, hmac_header: str, secret: str) -> bool:
    """Verify Shopify webhook HMAC signature"""
    try:
        if not hmac_header or not secret:
            logger.warning("Missing HMAC header or webhook secret")
            return False
        
        # Calculate expected HMAC
        digest = hmac.new(
            secret.encode('utf-8'),
            data,
            hashlib.sha256
        ).digest()
        computed_hmac = base64.b64encode(digest)
        
        # Compare with provided HMAC
        is_valid = hmac.compare_digest(computed_hmac, hmac_header.encode('utf-8'))
        
        if not is_valid:
            logger.warning("Invalid webhook signature")
        
        return is_valid
        
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False


async def verify_webhook_request(request: Request, merchant_webhook_secret: str = None) -> bool:
    """Verify incoming webhook request"""
    try:
        # Get HMAC header
        hmac_header = request.headers.get('X-Shopify-Hmac-SHA256')
        if not hmac_header:
            logger.warning("Missing X-Shopify-Hmac-SHA256 header")
            return False
        
        # Get raw body data
        body = await request.body()
        
        # Use merchant-specific secret or global secret
        secret = merchant_webhook_secret or settings.shopify_webhook_secret
        if not secret:
            logger.error("No webhook secret configured")
            return False
        
        return verify_webhook_signature(body, hmac_header, secret)
        
    except Exception as e:
        logger.error(f"Error verifying webhook request: {e}")
        return False


def extract_webhook_metadata(request: Request) -> Dict[str, str]:
    """Extract metadata from webhook headers"""
    return {
        'shop_domain': request.headers.get('X-Shopify-Shop-Domain', ''),
        'topic': request.headers.get('X-Shopify-Topic', ''),
        'webhook_id': request.headers.get('X-Shopify-Webhook-Id', ''),
        'api_version': request.headers.get('X-Shopify-API-Version', ''),
        'hmac': request.headers.get('X-Shopify-Hmac-SHA256', ''),
        'triggered_at': request.headers.get('X-Shopify-Triggered-At', ''),
    }


async def process_webhook_async(webhook_type: str, payload: Dict[str, Any], metadata: Dict[str, str], merchant_id: int):
    """Queue webhook for asynchronous processing"""
    try:
        task = QueueTask(
            id=f"shopify_webhook_{metadata.get('webhook_id', 'unknown')}_{datetime.utcnow().timestamp()}",
            queue_name="webhooks",
            task_type="webhook.process",
            payload={
                "type": f"shopify.{webhook_type}",
                "data": payload,
                "metadata": metadata,
                "merchant_id": merchant_id
            },
            priority=QueuePriority.HIGH if webhook_type in ["orders/create", "orders/paid"] else QueuePriority.NORMAL,
            max_retries=3
        )
        
        success = await async_queue.enqueue(task)
        if success:
            logger.info(f"Queued Shopify webhook {webhook_type} for processing")
        else:
            logger.error(f"Failed to queue Shopify webhook {webhook_type}")
            
        return success
        
    except Exception as e:
        logger.error(f"Error queueing Shopify webhook: {e}")
        return False


# Webhook handlers
async def handle_order_created(payload: Dict[str, Any], merchant_id: int) -> Dict[str, Any]:
    """Handle order created webhook"""
    try:
        order_data = payload
        order_id = order_data.get('id')
        order_number = order_data.get('order_number', order_data.get('name', ''))
        
        logger.info(f"Processing order created: {order_number} (ID: {order_id})")
        
        # Extract order information
        order_info = {
            'external_order_id': str(order_id),
            'order_number': order_number,
            'status': order_data.get('financial_status', 'pending'),
            'financial_status': order_data.get('financial_status'),
            'fulfillment_status': order_data.get('fulfillment_status'),
            'total_amount': float(order_data.get('total_price', 0)),
            'currency': order_data.get('currency', 'USD'),
            'customer_email': order_data.get('email'),
            'customer_phone': order_data.get('phone'),
            'customer_name': f"{order_data.get('billing_address', {}).get('first_name', '')} {order_data.get('billing_address', {}).get('last_name', '')}".strip(),
            'shipping_address': order_data.get('shipping_address', {}),
            'order_data': order_data,
            'order_date': datetime.fromisoformat(order_data.get('created_at', '').replace('Z', '+00:00')) if order_data.get('created_at') else None
        }
        
        # Store order in database
        from ...core.database import AsyncSessionLocal
        from ...core.models import Order, Customer, Merchant
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as db:
            # Get merchant
            merchant_result = await db.execute(select(Merchant).where(Merchant.id == merchant_id))
            merchant = merchant_result.scalar_one_or_none()
            
            if not merchant:
                logger.error(f"Merchant not found: {merchant_id}")
                return {"status": "error", "message": "Merchant not found"}
            
            # Find or create customer
            customer = None
            if order_info['customer_email']:
                customer_result = await db.execute(
                    select(Customer).where(
                        Customer.merchant_id == merchant_id,
                        Customer.email == order_info['customer_email']
                    )
                )
                customer = customer_result.scalar_one_or_none()
                
                if not customer:
                    # Create new customer
                    customer_data = order_data.get('customer', {})
                    customer = Customer(
                        merchant_id=merchant_id,
                        external_id=str(customer_data.get('id', '')),
                        email=order_info['customer_email'],
                        phone_number=order_info['customer_phone'],
                        first_name=customer_data.get('first_name'),
                        last_name=customer_data.get('last_name'),
                        full_name=f"{customer_data.get('first_name', '')} {customer_data.get('last_name', '')}".strip()
                    )
                    db.add(customer)
                    await db.flush()
            
            # Check if order already exists
            existing_order = await db.execute(
                select(Order).where(
                    Order.merchant_id == merchant_id,
                    Order.external_order_id == order_info['external_order_id']
                )
            )
            
            if existing_order.scalar_one_or_none():
                logger.info(f"Order already exists: {order_number}")
                return {"status": "duplicate", "order_number": order_number}
            
            # Create new order
            new_order = Order(
                merchant_id=merchant_id,
                customer_id=customer.id if customer else None,
                **order_info
            )
            
            db.add(new_order)
            await db.commit()
            
            logger.info(f"Successfully stored order: {order_number}")
            
            # Trigger order confirmation workflow
            await trigger_order_confirmation(new_order, merchant, customer)
            
            return {"status": "success", "order_id": new_order.id, "order_number": order_number}
            
    except Exception as e:
        logger.error(f"Error processing order created webhook: {e}")
        raise ShopifyAPIException(f"Failed to process order: {str(e)}")


async def handle_order_updated(payload: Dict[str, Any], merchant_id: int) -> Dict[str, Any]:
    """Handle order updated webhook"""
    try:
        order_data = payload
        order_id = str(order_data.get('id'))
        order_number = order_data.get('order_number', order_data.get('name', ''))
        
        logger.info(f"Processing order updated: {order_number}")
        
        from ...core.database import AsyncSessionLocal
        from ...core.models import Order
        from sqlalchemy import select, update
        
        async with AsyncSessionLocal() as db:
            # Find existing order
            result = await db.execute(
                select(Order).where(
                    Order.merchant_id == merchant_id,
                    Order.external_order_id == order_id
                )
            )
            existing_order = result.scalar_one_or_none()
            
            if not existing_order:
                logger.warning(f"Order not found for update: {order_number}")
                return {"status": "not_found", "order_number": order_number}
            
            # Update order data
            update_data = {
                'status': order_data.get('financial_status', existing_order.status),
                'financial_status': order_data.get('financial_status'),
                'fulfillment_status': order_data.get('fulfillment_status'),
                'total_amount': float(order_data.get('total_price', existing_order.total_amount)),
                'order_data': order_data,
                'updated_at': datetime.utcnow()
            }
            
            # Check for fulfillment updates
            if order_data.get('fulfillment_status') and order_data['fulfillment_status'] != existing_order.fulfillment_status:
                if order_data['fulfillment_status'] == 'fulfilled':
                    update_data['shipped_at'] = datetime.utcnow()
                    
                    # Extract tracking information
                    fulfillments = order_data.get('fulfillments', [])
                    if fulfillments:
                        tracking_info = fulfillments[0].get('tracking_info', {})
                        update_data['tracking_number'] = tracking_info.get('number')
                        update_data['tracking_url'] = tracking_info.get('url')
            
            await db.execute(
                update(Order).where(Order.id == existing_order.id).values(**update_data)
            )
            await db.commit()
            
            logger.info(f"Successfully updated order: {order_number}")
            
            # Trigger status update notifications
            await trigger_order_status_update(existing_order, update_data)
            
            return {"status": "success", "order_number": order_number}
            
    except Exception as e:
        logger.error(f"Error processing order updated webhook: {e}")
        raise ShopifyAPIException(f"Failed to update order: {str(e)}")


async def handle_order_fulfilled(payload: Dict[str, Any], merchant_id: int) -> Dict[str, Any]:
    """Handle order fulfilled webhook"""
    try:
        order_data = payload
        order_id = str(order_data.get('id'))
        
        logger.info(f"Processing order fulfilled: {order_id}")
        
        # Update order fulfillment status
        result = await handle_order_updated(payload, merchant_id)
        
        # Send fulfillment notification to customer
        if result.get("status") == "success":
            await trigger_fulfillment_notification(order_id, merchant_id)
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing order fulfilled webhook: {e}")
        raise ShopifyAPIException(f"Failed to process fulfillment: {str(e)}")


async def handle_customer_created(payload: Dict[str, Any], merchant_id: int) -> Dict[str, Any]:
    """Handle customer created webhook"""
    try:
        customer_data = payload
        customer_id = str(customer_data.get('id'))
        
        logger.info(f"Processing customer created: {customer_id}")
        
        from ...core.database import AsyncSessionLocal
        from ...core.models import Customer
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as db:
            # Check if customer already exists
            existing_customer = await db.execute(
                select(Customer).where(
                    Customer.merchant_id == merchant_id,
                    Customer.external_id == customer_id
                )
            )
            
            if existing_customer.scalar_one_or_none():
                logger.info(f"Customer already exists: {customer_id}")
                return {"status": "duplicate", "customer_id": customer_id}
            
            # Create new customer
            new_customer = Customer(
                merchant_id=merchant_id,
                external_id=customer_id,
                email=customer_data.get('email'),
                phone_number=customer_data.get('phone'),
                first_name=customer_data.get('first_name'),
                last_name=customer_data.get('last_name'),
                full_name=f"{customer_data.get('first_name', '')} {customer_data.get('last_name', '')}".strip()
            )
            
            db.add(new_customer)
            await db.commit()
            
            logger.info(f"Successfully created customer: {customer_id}")
            
            return {"status": "success", "customer_id": new_customer.id}
            
    except Exception as e:
        logger.error(f"Error processing customer created webhook: {e}")
        raise ShopifyAPIException(f"Failed to create customer: {str(e)}")


async def handle_app_uninstalled(payload: Dict[str, Any], merchant_id: int) -> Dict[str, Any]:
    """Handle app uninstalled webhook"""
    try:
        logger.info(f"Processing app uninstalled for merchant: {merchant_id}")
        
        from ...core.database import AsyncSessionLocal
        from ...core.models import Merchant
        from sqlalchemy import update
        
        async with AsyncSessionLocal() as db:
            # Deactivate merchant
            await db.execute(
                update(Merchant)
                .where(Merchant.id == merchant_id)
                .values(is_active=False, shopify_access_token=None)
            )
            await db.commit()
            
            logger.info(f"Deactivated merchant after app uninstall: {merchant_id}")
            
            return {"status": "success", "merchant_id": merchant_id}
            
    except Exception as e:
        logger.error(f"Error processing app uninstalled webhook: {e}")
        raise ShopifyAPIException(f"Failed to process uninstall: {str(e)}")


# Notification triggers
async def trigger_order_confirmation(order, merchant, customer):
    """Trigger order confirmation message to customer"""
    if not customer or not customer.whatsapp_id:
        return
    
    # Queue WhatsApp message
    from ...core.queue import QueueTask, QueuePriority
    
    task = QueueTask(
        id=f"order_confirmation_{order.id}_{datetime.utcnow().timestamp()}",
        queue_name="notifications",
        task_type="whatsapp.send_message",
        payload={
            "recipient": customer.whatsapp_id,
            "template": "order_confirmation",
            "order_id": order.id,
            "merchant_id": merchant.id
        },
        priority=QueuePriority.HIGH
    )
    
    await async_queue.enqueue(task)


async def trigger_order_status_update(order, update_data):
    """Trigger order status update notification"""
    # Implementation for status update notifications
    pass


async def trigger_fulfillment_notification(order_id: str, merchant_id: int):
    """Trigger fulfillment notification"""
    # Implementation for fulfillment notifications
    pass