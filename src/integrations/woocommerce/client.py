import asyncio
import httpx
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from loguru import logger
import base64

from ...core.config import settings
from ...core.exceptions import WooCommerceAPIException
from ...core.cache import cache_service


class WooCommerceAPIClient:
    """WooCommerce REST API client with authentication and rate limiting"""
    
    def __init__(self, store_url: str, consumer_key: str, consumer_secret: str):
        self.store_url = store_url.rstrip('/')
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.api_base = f"{self.store_url}/wp-json/wc/v3"
        
        # Rate limiting settings (WooCommerce doesn't have strict limits but be respectful)
        self.rate_limit_calls = 60  # 60 requests per minute
        self.rate_limit_window = 60
        
        # Retry settings
        self.max_retries = 3
        self.backoff_factor = 2
    
    def _get_auth_header(self) -> str:
        """Generate basic authentication header"""
        credentials = f"{self.consumer_key}:{self.consumer_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded_credentials}"
    
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
        
        url = f"{self.api_base}/{endpoint.lstrip('/')}"
        headers = {
            'Authorization': self._get_auth_header(),
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
                    logger.warning(f"Rate limited by WooCommerce. Waiting {retry_after} seconds...")
                    await asyncio.sleep(retry_after)
                    if retry_count < self.max_retries:
                        return await self._make_request(method, endpoint, params, data, retry_count + 1)
                    else:
                        raise WooCommerceAPIException("Rate limit exceeded, max retries reached")
                
                elif response.status_code >= 500:
                    if retry_count < self.max_retries:
                        wait_time = self.backoff_factor ** retry_count
                        logger.warning(f"Server error {response.status_code}. Retrying in {wait_time} seconds...")
                        await asyncio.sleep(wait_time)
                        return await self._make_request(method, endpoint, params, data, retry_count + 1)
                    else:
                        raise WooCommerceAPIException(f"Server error {response.status_code}, max retries reached")
                
                elif response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error_message = error_data.get('message', f'HTTP {response.status_code}')
                    except:
                        error_message = f'HTTP {response.status_code}'
                    raise WooCommerceAPIException(f"API error: {error_message}")
                
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
                raise WooCommerceAPIException(f"Network error: {str(e)}")
    
    async def _check_rate_limit(self):
        """Check if we're within rate limits"""
        rate_key = f"woocommerce_rate_limit:{self.store_url}"
        current_requests = await cache_service.get(rate_key) or 0
        
        if current_requests >= self.rate_limit_calls:
            wait_time = self.rate_limit_window
            logger.info(f"Rate limit reached for {self.store_url}. Waiting {wait_time} seconds...")
            await asyncio.sleep(wait_time)
    
    async def _update_rate_limit(self):
        """Update rate limit counter"""
        rate_key = f"woocommerce_rate_limit:{self.store_url}"
        await cache_service.increment(rate_key)
        # Set expiry if it's a new key
        if not await cache_service.exists(rate_key):
            await cache_service.set_with_expire(rate_key, 1, self.rate_limit_window)
    
    async def get(self, endpoint: str, params: Dict = None) -> Any:
        """GET request"""
        response = await self._make_request('GET', endpoint, params=params)
        return response.json()
    
    async def post(self, endpoint: str, data: Dict = None) -> Any:
        """POST request"""
        response = await self._make_request('POST', endpoint, data=data)
        return response.json()
    
    async def put(self, endpoint: str, data: Dict = None) -> Any:
        """PUT request"""
        response = await self._make_request('PUT', endpoint, data=data)
        return response.json()
    
    async def delete(self, endpoint: str) -> bool:
        """DELETE request"""
        response = await self._make_request('DELETE', endpoint)
        return response.status_code == 200
    
    # System information
    async def get_system_status(self) -> Dict[str, Any]:
        """Get WooCommerce system status"""
        return await self.get('/system_status')
    
    # Order methods
    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        cache_key = f"woocommerce_order:{self.store_url}:{order_id}"
        
        # Try cache first
        cached_order = await cache_service.get(cache_key)
        if cached_order:
            return cached_order
        
        try:
            order = await self.get(f'/orders/{order_id}')
            
            # Cache for 5 minutes
            await cache_service.cache_with_jitter(cache_key, order, cache_service.TTL_ORDER_CACHE)
            
            return order
        except WooCommerceAPIException:
            return None
    
    async def get_orders(
        self,
        status: str = None,
        customer: int = None,
        product: int = None,
        dp: int = 2,  # decimal places
        after: datetime = None,
        before: datetime = None,
        page: int = 1,
        per_page: int = 50
    ) -> List[Dict[str, Any]]:
        """Get orders with filters"""
        params = {
            'page': page,
            'per_page': min(per_page, 100),  # Max 100 per request
            'dp': dp
        }
        
        if status:
            params['status'] = status
        if customer:
            params['customer'] = customer
        if product:
            params['product'] = product
        if after:
            params['after'] = after.isoformat()
        if before:
            params['before'] = before.isoformat()
        
        return await self.get('/orders', params)
    
    async def update_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update order"""
        order = await self.put(f'/orders/{order_id}', order_data)
        
        # Invalidate cache
        cache_key = f"woocommerce_order:{self.store_url}:{order_id}"
        await cache_service.delete(cache_key)
        
        return order
    
    async def get_order_notes(self, order_id: str) -> List[Dict[str, Any]]:
        """Get order notes"""
        return await self.get(f'/orders/{order_id}/notes')
    
    async def create_order_note(self, order_id: str, note: str, customer_note: bool = False) -> Dict[str, Any]:
        """Create order note"""
        note_data = {
            'note': note,
            'customer_note': customer_note
        }
        return await self.post(f'/orders/{order_id}/notes', note_data)
    
    # Customer methods
    async def get_customer(self, customer_id: str) -> Optional[Dict[str, Any]]:
        """Get customer by ID"""
        cache_key = f"woocommerce_customer:{self.store_url}:{customer_id}"
        
        # Try cache first
        cached_customer = await cache_service.get(cache_key)
        if cached_customer:
            return cached_customer
        
        try:
            customer = await self.get(f'/customers/{customer_id}')
            
            # Cache for 10 minutes
            await cache_service.cache_with_jitter(cache_key, customer, cache_service.TTL_ORDER_CACHE * 2)
            
            return customer
        except WooCommerceAPIException:
            return None
    
    async def get_customers(
        self,
        search: str = None,
        email: str = None,
        role: str = None,
        page: int = 1,
        per_page: int = 50
    ) -> List[Dict[str, Any]]:
        """Get customers with filters"""
        params = {
            'page': page,
            'per_page': min(per_page, 100)
        }
        
        if search:
            params['search'] = search
        if email:
            params['email'] = email
        if role:
            params['role'] = role
        
        return await self.get('/customers', params)
    
    async def update_customer(self, customer_id: str, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update customer"""
        customer = await self.put(f'/customers/{customer_id}', customer_data)
        
        # Invalidate cache
        cache_key = f"woocommerce_customer:{self.store_url}:{customer_id}"
        await cache_service.delete(cache_key)
        
        return customer
    
    # Product methods
    async def get_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Get product by ID"""
        cache_key = f"woocommerce_product:{self.store_url}:{product_id}"
        
        # Try cache first
        cached_product = await cache_service.get(cache_key)
        if cached_product:
            return cached_product
        
        try:
            product = await self.get(f'/products/{product_id}')
            
            # Cache for 30 minutes (products change less frequently)
            await cache_service.cache_with_jitter(cache_key, product, cache_service.TTL_SHORT * 30)
            
            return product
        except WooCommerceAPIException:
            return None
    
    async def get_products(
        self,
        search: str = None,
        category: str = None,
        tag: str = None,
        status: str = 'publish',
        page: int = 1,
        per_page: int = 50
    ) -> List[Dict[str, Any]]:
        """Get products with filters"""
        params = {
            'page': page,
            'per_page': min(per_page, 100),
            'status': status
        }
        
        if search:
            params['search'] = search
        if category:
            params['category'] = category
        if tag:
            params['tag'] = tag
        
        return await self.get('/products', params)
    
    # Category methods
    async def get_product_categories(self, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        """Get product categories"""
        params = {
            'page': page,
            'per_page': min(per_page, 100)
        }
        return await self.get('/products/categories', params)
    
    # Tax methods
    async def get_tax_rates(self) -> List[Dict[str, Any]]:
        """Get tax rates"""
        return await self.get('/taxes')
    
    # Shipping methods
    async def get_shipping_zones(self) -> List[Dict[str, Any]]:
        """Get shipping zones"""
        return await self.get('/shipping/zones')
    
    async def get_shipping_methods(self, zone_id: str) -> List[Dict[str, Any]]:
        """Get shipping methods for a zone"""
        return await self.get(f'/shipping/zones/{zone_id}/methods')
    
    # Coupon methods
    async def get_coupons(self, code: str = None, page: int = 1, per_page: int = 50) -> List[Dict[str, Any]]:
        """Get coupons"""
        params = {
            'page': page,
            'per_page': min(per_page, 100)
        }
        
        if code:
            params['code'] = code
        
        return await self.get('/coupons', params)
    
    # Refund methods
    async def get_order_refunds(self, order_id: str) -> List[Dict[str, Any]]:
        """Get refunds for an order"""
        return await self.get(f'/orders/{order_id}/refunds')
    
    async def create_refund(self, order_id: str, refund_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create refund for order"""
        return await self.post(f'/orders/{order_id}/refunds', refund_data)
    
    # Webhook methods
    async def get_webhooks(self) -> List[Dict[str, Any]]:
        """Get all webhooks"""
        return await self.get('/webhooks')
    
    async def create_webhook(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create webhook"""
        return await self.post('/webhooks', webhook_data)
    
    async def delete_webhook(self, webhook_id: str) -> bool:
        """Delete webhook"""
        return await self.delete(f'/webhooks/{webhook_id}')
    
    # Reports methods
    async def get_sales_report(self, period: str = 'week') -> Dict[str, Any]:
        """Get sales report"""
        params = {'period': period}
        return await self.get('/reports/sales', params)
    
    async def get_top_sellers_report(self, period: str = 'week') -> List[Dict[str, Any]]:
        """Get top sellers report"""
        params = {'period': period}
        return await self.get('/reports/top_sellers', params)


def get_woocommerce_client(merchant) -> WooCommerceAPIClient:
    """Factory function to create WooCommerce client for merchant"""
    if not merchant.woocommerce_consumer_key or not merchant.woocommerce_consumer_secret or not merchant.woocommerce_url:
        raise WooCommerceAPIException("Missing WooCommerce credentials for merchant")
    
    return WooCommerceAPIClient(
        store_url=merchant.woocommerce_url,
        consumer_key=merchant.woocommerce_consumer_key,
        consumer_secret=merchant.woocommerce_consumer_secret
    )