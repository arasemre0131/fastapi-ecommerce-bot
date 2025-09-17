from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from urllib.parse import parse_qs
import uuid
from loguru import logger

from .auth import shopify_oauth
from .webhooks import (
    verify_webhook_request, extract_webhook_metadata, process_webhook_async,
    handle_order_created, handle_order_updated, handle_order_fulfilled,
    handle_customer_created, handle_app_uninstalled
)
from .client import get_shopify_client
from ...auth.dependencies import get_current_user
from ...core.database import get_db
from ...core.models import Merchant
from ...core.exceptions import ShopifyAPIException, ValidationException
from ...core.cache import cache_service


router = APIRouter(prefix="/shopify", tags=["Shopify Integration"])


@router.get("/auth/install")
async def initiate_shopify_install(
    shop: str = Query(..., description="Shop domain (without .myshopify.com)"),
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Initiate Shopify app installation process"""
    try:
        # Validate shop domain
        if not shop or len(shop) < 3:
            raise ValidationException("Invalid shop domain")
        
        # Generate CSRF state token
        state = str(uuid.uuid4())
        
        # Store state in cache for verification (expires in 10 minutes)
        state_data = {
            "user_id": current_user.id,
            "shop": shop,
            "timestamp": "current_time"
        }
        await cache_service.set_with_expire(f"shopify_oauth_state:{state}", state_data, 600)
        
        # Generate authorization URL
        auth_url, csrf_state = shopify_oauth.generate_auth_url(shop, state=state)
        
        logger.info(f"Initiated Shopify installation for shop: {shop}, user: {current_user.id}")
        
        return {
            "authorization_url": auth_url,
            "state": csrf_state,
            "shop": f"{shop}.myshopify.com"
        }
        
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error initiating Shopify install: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Installation failed")


@router.get("/auth/callback")
async def shopify_oauth_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    shop: str = Query(...),
    hmac: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Handle Shopify OAuth callback"""
    try:
        # Verify HMAC signature
        query_string = str(request.url.query)
        if not shopify_oauth.verify_installation_request(query_string):
            raise ValidationException("Invalid installation request signature")
        
        # Verify state token
        state_data = await cache_service.get(f"shopify_oauth_state:{state}")
        if not state_data:
            raise ValidationException("Invalid or expired state token")
        
        user_id = state_data["user_id"]
        expected_shop = state_data["shop"]
        
        # Verify shop matches
        if shop.replace('.myshopify.com', '') != expected_shop:
            raise ValidationException("Shop domain mismatch")
        
        # Exchange code for access token
        token_data = await shopify_oauth.exchange_code_for_token(shop, code, state)
        
        # Get shop information
        shop_info = await shopify_oauth.get_shop_info(shop, token_data["access_token"])
        if not shop_info:
            raise ShopifyAPIException("Failed to retrieve shop information")
        
        # Create or update merchant record
        from sqlalchemy import select, update
        
        # Check if merchant already exists
        existing_merchant = await db.execute(
            select(Merchant).where(
                Merchant.shopify_shop_domain == shop,
                Merchant.platform_type == "shopify"
            )
        )
        merchant = existing_merchant.scalar_one_or_none()
        
        if merchant:
            # Update existing merchant
            await db.execute(
                update(Merchant)
                .where(Merchant.id == merchant.id)
                .values(
                    shopify_access_token=token_data["access_token"],
                    is_active=True,
                    name=shop_info.get("name", merchant.name),
                    email=shop_info.get("email", merchant.email),
                    phone=shop_info.get("phone", merchant.phone),
                    website=shop_info.get("domain", merchant.website)
                )
            )
            await db.commit()
            
            logger.info(f"Updated existing Shopify merchant: {shop}")
        else:
            # Create new merchant
            merchant = Merchant(
                name=shop_info.get("name", shop),
                email=shop_info.get("email", ""),
                phone=shop_info.get("phone"),
                website=shop_info.get("domain"),
                platform_type="shopify",
                platform_domain=shop,
                shopify_shop_domain=shop,
                shopify_access_token=token_data["access_token"],
                is_active=True
            )
            
            db.add(merchant)
            await db.commit()
            await db.refresh(merchant)
            
            logger.info(f"Created new Shopify merchant: {shop}")
        
        # Set up required webhooks
        webhook_base_url = f"https://yourdomain.com{request.url.path.replace('/auth/callback', '')}"
        webhook_results = await shopify_oauth.setup_required_webhooks(
            shop, token_data["access_token"], webhook_base_url
        )
        
        # Clean up state token
        await cache_service.delete(f"shopify_oauth_state:{state}")
        
        # Return success response with merchant info
        return {
            "status": "success",
            "message": "Shopify integration completed successfully",
            "merchant_id": merchant.id,
            "shop": shop,
            "webhooks_created": webhook_results
        }
        
    except ValidationException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ShopifyAPIException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error in Shopify OAuth callback: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OAuth callback failed")


# Webhook endpoints
@router.post("/webhooks/orders_create")
async def webhook_orders_create(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle order created webhook"""
    return await process_webhook("orders/create", request, db, handle_order_created)


@router.post("/webhooks/orders_updated")
async def webhook_orders_updated(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle order updated webhook"""
    return await process_webhook("orders/updated", request, db, handle_order_updated)


@router.post("/webhooks/orders_paid")
async def webhook_orders_paid(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle order paid webhook"""
    return await process_webhook("orders/paid", request, db, handle_order_updated)


@router.post("/webhooks/orders_cancelled")
async def webhook_orders_cancelled(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle order cancelled webhook"""
    return await process_webhook("orders/cancelled", request, db, handle_order_updated)


@router.post("/webhooks/orders_fulfilled")
async def webhook_orders_fulfilled(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle order fulfilled webhook"""
    return await process_webhook("orders/fulfilled", request, db, handle_order_fulfilled)


@router.post("/webhooks/customers_create")
async def webhook_customers_create(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle customer created webhook"""
    return await process_webhook("customers/create", request, db, handle_customer_created)


@router.post("/webhooks/customers_update")
async def webhook_customers_update(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle customer updated webhook"""
    return await process_webhook("customers/update", request, db, handle_customer_created)


@router.post("/webhooks/app_uninstalled")
async def webhook_app_uninstalled(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle app uninstalled webhook"""
    return await process_webhook("app/uninstalled", request, db, handle_app_uninstalled)


async def process_webhook(webhook_type: str, request: Request, db: AsyncSession, handler_func):
    """Generic webhook processor"""
    try:
        # Extract metadata from headers
        metadata = extract_webhook_metadata(request)
        shop_domain = metadata.get("shop_domain")
        
        if not shop_domain:
            logger.warning("Missing shop domain in webhook headers")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing shop domain")
        
        # Find merchant by shop domain
        from sqlalchemy import select
        merchant_result = await db.execute(
            select(Merchant).where(
                Merchant.shopify_shop_domain == shop_domain,
                Merchant.platform_type == "shopify",
                Merchant.is_active == True
            )
        )
        merchant = merchant_result.scalar_one_or_none()
        
        if not merchant:
            logger.warning(f"Merchant not found for shop: {shop_domain}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        
        # Verify webhook signature
        is_valid = await verify_webhook_request(request, merchant.shopify_webhook_secret)
        if not is_valid:
            logger.warning(f"Invalid webhook signature from {shop_domain}")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature")
        
        # Parse webhook payload
        payload = await request.json()
        
        # Log webhook receipt
        logger.info(f"Received Shopify webhook: {webhook_type} from {shop_domain}")
        
        # Process webhook asynchronously
        success = await process_webhook_async(webhook_type, payload, metadata, merchant.id)
        
        if not success:
            logger.error(f"Failed to queue webhook: {webhook_type}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing failed")
        
        return Response(status_code=200)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook {webhook_type}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook processing error")


# API endpoints for merchant management
@router.get("/merchants/{merchant_id}/orders")
async def get_merchant_orders(
    merchant_id: int,
    limit: int = Query(50, le=250),
    status: Optional[str] = None,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get orders for a Shopify merchant"""
    try:
        # Get merchant
        from sqlalchemy import select
        merchant_result = await db.execute(
            select(Merchant).where(
                Merchant.id == merchant_id,
                Merchant.platform_type == "shopify",
                Merchant.is_active == True
            )
        )
        merchant = merchant_result.scalar_one_or_none()
        
        if not merchant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        
        # Create Shopify client
        client = get_shopify_client(merchant)
        
        # Get orders from Shopify
        orders = await client.get_orders(status=status, limit=limit)
        
        return {
            "orders": orders,
            "count": len(orders),
            "merchant_id": merchant_id
        }
        
    except ShopifyAPIException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting merchant orders: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get orders")


@router.get("/merchants/{merchant_id}/orders/{order_id}")
async def get_merchant_order(
    merchant_id: int,
    order_id: str,
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get specific order for a Shopify merchant"""
    try:
        # Get merchant
        from sqlalchemy import select
        merchant_result = await db.execute(
            select(Merchant).where(
                Merchant.id == merchant_id,
                Merchant.platform_type == "shopify",
                Merchant.is_active == True
            )
        )
        merchant = merchant_result.scalar_one_or_none()
        
        if not merchant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found")
        
        # Create Shopify client
        client = get_shopify_client(merchant)
        
        # Get order from Shopify
        order = await client.get_order(order_id)
        
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        
        return order
        
    except ShopifyAPIException as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting merchant order: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get order")