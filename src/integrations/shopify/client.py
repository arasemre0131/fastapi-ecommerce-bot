import asyncio
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from loguru import logger

from ...core.config import settings
from ...core.exceptions import ShopifyAPIException
from ...core.cache import cache_service


class ShopifyAPIClient:
    """Shopify API client with rate limiting and retry logic"""
    
    def __init__(self, shop_domain: str, access_token: str):
        self.shop_domain = shop_domain.replace('.myshopify.com', '') + '.myshopify.com'
        self.access_token = access_token
        self.api_version = settings.shopify_api_version
        self.base_url = f"https://{self.shop_domain}/admin/api/{self.api_version}"
        
        # Rate limiting settings (Shopify allows 40 requests per second)
        self.rate_limit_calls = 35  # Conservative limit
        self.rate_limit_window = 1  # 1 second
        
        # Retry settings
        self.max_retries = 3
        self.backoff_factor = 2
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        data: Dict = None,
        retry_count: int = 0
    ) -> httpx.Response:
        """Make API request with rate limiting and retry logic"""
        
        # Check rate limit
        await self._check_rate_limit()
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            'X-Shopify-Access-Token': self.access_token,
            'Content-Type': 'application/json',
            'User-Agent': f'ECommerce-Bot/{settings.version}'
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data
                )
                
                # Handle rate limiting (429) and server errors (5xx)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited by Shopify. Waiting {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                    if retry_count < self.max_retries:
                        return await self._make_request(method, endpoint, params, data, retry_count + 1)
                    else:
                        raise ShopifyAPIException("Rate limit exceeded, max retries reached")
                
                elif response.status_code >= 500:
                    if retry_count < self.max_retries:
                        wait_time = self.backoff_factor ** retry_count
                        logger.warning(f"Server error {response.status_code}. Retrying in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                        return await self._make_request(method, endpoint, params, data, retry_count + 1)
                    else:
                        raise ShopifyAPIException(f"Server error {response.status_code}, max retries reached")
                
                elif response.status_code >= 400:
                    error_data = response.json() if response.content else {}
                    error_message = error_data.get('errors', f'HTTP {response.status_code}')
                    raise ShopifyAPIException(f"API error: {error_message}")
                
                # Update rate limit tracking
                await self._update_rate_limit()
                
                return response
                
        except httpx.RequestError as e:
            if retry_count < self.max_retries:
                wait_time = self.backoff_factor ** retry_count
                logger.warning(f"Network error: {e}. Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
                return await self._make_request(method, endpoint, params, data, retry_count + 1)
            else:
                raise ShopifyAPIException(f"Network error: {str(e)}")
    
    async def _check_rate_limit(self):
        """Check if we're within rate limits"""
        rate_key = f"shopify_rate_limit:{self.shop_domain}"
        current_requests = await cache_service.get(rate_key) or 0
        
        if current_requests >= self.rate_limit_calls:
            wait_time = self.rate_limit_window
            logger.info(f"Rate limit reached for {self.shop_domain}. Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
    
    async def _update_rate_limit(self):
        """Update rate limit counter"""
        rate_key = f"shopify_rate_limit:{self.shop_domain}"
        await cache_service.increment(rate_key)
        # Set expiry if it's a new key
        if not await cache_service.exists(rate_key):
            await cache_service.set_with_expire(rate_key, 1, self.rate_limit_window)
    
    async def get(self, endpoint: str, params: Dict = None) -> Dict[str, Any]:
        """GET request"""
        response = await self._make_request('GET', endpoint, params=params)
        return response.json()
    
    async def post(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """POST request"""
        response = await self._make_request('POST', endpoint, data=data)
        return response.json()
    
    async def put(self, endpoint: str, data: Dict = None) -> Dict[str, Any]:
        """PUT request"""
        response = await self._make_request('PUT', endpoint, data=data)
        return response.json()
    
    async def delete(self, endpoint: str) -> bool:
        """DELETE request"""
        response = await self._make_request('DELETE', endpoint)
        return response.status_code == 200
    
    # Shop methods
    async def get_shop_info(self) -> Dict[str, Any]:
        """Get shop information"""
        cache_key = f"shopify_shop_info:{self.shop_domain}"
        
        # Try cache first
        cached_info = await cache_service.get(cache_key)
        if cached_info:
            return cached_info
        
        response = await self.get('/shop.json')
        shop_info = response.get('shop', {})
        
        # Cache for 1 hour
        await cache_service.cache_with_jitter(cache_key, shop_info, cache_service.TTL_SHORT * 60)
        
        return shop_info
    
    # Order methods
    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        cache_key = f"shopify_order:{self.shop_domain}:{order_id}"
        
        # Try cache first
        cached_order = await cache_service.get(cache_key)
        if cached_order:
            return cached_order
        
        try:
            response = await self.get(f'/orders/{order_id}.json')
            order = response.get('order', {})
            
            # Cache for 5 minutes
            await cache_service.cache_with_jitter(cache_key, order, cache_service.TTL_ORDER_CACHE)
            
            return order
        except ShopifyAPIException:
            return None
    
    async def get_orders(
        self,
        status: str = None,
        financial_status: str = None,
        fulfillment_status: str = None,
        since_id: str = None,
        created_at_min: datetime = None,
        created_at_max: datetime = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get orders with filters"""
        params = {'limit': min(limit, 250)}  # Max 250 per request
        
        if status:
            params['status'] = status
        if financial_status:
            params['financial_status'] = financial_status
        if fulfillment_status:
            params['fulfillment_status'] = fulfillment_status
        if since_id:
            params['since_id'] = since_id
        if created_at_min:
            params['created_at_min'] = created_at_min.isoformat()
        if created_at_max:
            params['created_at_max'] = created_at_max.isoformat()
        
        response = await self.get('/orders.json', params)
        return response.get('orders', [])
    
    async def update_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update order"""
        data = {'order': order_data}
        response = await self.put(f'/orders/{order_id}.json', data)
        
        # Invalidate cache
        cache_key = f"shopify_order:{self.shop_domain}:{order_id}"
        await cache_service.delete(cache_key)
        
        return response.get('order', {})
    
    # Customer methods
    async def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """Get customer by ID"""
        cache_key = f"shopify_customer:{self.shop_domain}:{customer_id}"
        
        # Try cache first
        cached_customer = await cache_service.get(cache_key)
        if cached_customer:
            return cached_customer
        
        try:
            response = await self.get(f'/customers/{customer_id}.json')
            customer = response.get('customer', {})
            
            # Cache for 10 minutes
            await cache_service.cache_with_jitter(cache_key, customer, cache_service.TTL_ORDER_CACHE * 2)
            
            return customer
        except ShopifyAPIException:
            return None
    
    async def search_customers(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search customers"""
        params = {
            'query': query,
            'limit': min(limit, 250)
        }
        
        response = await self.get('/customers/search.json', params)
        return response.get('customers', [])
    
    async def update_customer(self, customer_id: str, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update customer"""
        data = {'customer': customer_data}
        response = await self.put(f'/customers/{customer_id}.json', data)
        
        # Invalidate cache
        cache_key = f"shopify_customer:{self.shop_domain}:{customer_id}"
        await cache_service.delete(cache_key)
        
        return response.get('customer', {})
    
    # Product methods
    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Get product by ID"""
        cache_key = f"shopify_product:{self.shop_domain}:{product_id}"
        
        # Try cache first
        cached_product = await cache_service.get(cache_key)
        if cached_product:
            return cached_product
        
        try:
            response = await self.get(f'/products/{product_id}.json')
            product = response.get('product', {})
            
            # Cache for 30 minutes (products change less frequently)
            await cache_service.cache_with_jitter(cache_key, product, cache_service.TTL_SHORT * 30)
            
            return product
        except ShopifyAPIException:
            return None
    
    async def search_products(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Search products"""
        params = {
            'title': query,
            'limit': min(limit, 250)
        }
        
        response = await self.get('/products.json', params)
        return response.get('products', [])
    
    # Fulfillment methods
    async def get_fulfillments(self, order_id: str) -> List[Dict[str, Any]]:
        """Get fulfillments for an order"""
        response = await self.get(f'/orders/{order_id}/fulfillments.json')
        return response.get('fulfillments', [])
    
    async def create_fulfillment(self, order_id: str, fulfillment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create fulfillment for order"""
        data = {'fulfillment': fulfillment_data}
        response = await self.post(f'/orders/{order_id}/fulfillments.json', data)
        return response.get('fulfillment', {})
    
    # Webhook methods
    async def get_webhooks(self) -> List[Dict[str, Any]]:
        """Get all webhooks"""
        response = await self.get('/webhooks.json')
        return response.get('webhooks', [])
    
    async def create_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create webhook"""
        data = {'webhook': webhook_data}
        response = await self.post('/webhooks.json', data)
        return response.get('webhook', {})
    
    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete webhook"""
        return await self.delete(f'/webhooks/{webhook_id}.json')


def get_shopify_client(merchant) -> ShopifyAPIClient:
    """Factory function to create Shopify client for merchant"""
    if not merchant.shopify_access_token or not merchant.shopify_shop_domain:
        raise ShopifyAPIException("Missing Shopify credentials for merchant")
    
    return ShopifyAPIClient(
        shop_domain=merchant.shopify_shop_domain,
        access_token=merchant.shopify_access_token
    )