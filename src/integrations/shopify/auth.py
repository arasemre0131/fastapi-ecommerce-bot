import hmac
import hashlib
import secrets
from urllib.parse import urlencode, parse_qs
from typing import Dict, Optional, Tuple
import httpx
from loguru import logger

from ...core.config import settings
from ...core.exceptions import ShopifyAPIException


class ShopifyOAuth:
    def __init__(self, client_id: str = None, client_secret: str = None, redirect_uri: str = None):
        self.client_id = client_id or settings.shopify_client_id
        self.client_secret = client_secret or settings.shopify_client_secret
        self.redirect_uri = redirect_uri or f"{settings.api_v1_prefix}/shopify/oauth/callback"
        
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Shopify client ID and secret must be provided")
        
        # Default scopes for e-commerce support bot
        self.default_scopes = [
            "read_orders",
            "read_products", 
            "read_customers",
            "read_fulfillments",
            "read_inventory",
            "read_shipping",
            "write_orders",  # For order updates
            "write_customers"  # For customer communication tracking
        ]
    
    def verify_installation_request(self, query_string: str) -> bool:
        """Verify Shopify installation request HMAC signature"""
        try:
            params = parse_qs(query_string)
            hmac_param = params.pop('hmac', [None])[0]
            
            if not hmac_param:
                logger.warning("Missing HMAC parameter in Shopify installation request")
                return False
            
            # Reconstruct query string without HMAC
            sorted_params = sorted(params.items())
            query_string_without_hmac = '&'.join([f'{k}={v[0]}' for k, v in sorted_params])
            
            # Calculate expected HMAC
            expected_digest = hmac.new(
                self.client_secret.encode('utf-8'),
                query_string_without_hmac.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Compare with provided HMAC
            is_valid = hmac.compare_digest(expected_digest, hmac_param)
            
            if not is_valid:
                logger.warning(f"Invalid HMAC in Shopify installation request: expected {expected_digest}, got {hmac_param}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying Shopify installation request: {e}")
            return False
    
    def generate_auth_url(self, shop_domain: str, scopes: list = None, state: str = None) -> Tuple[str, str]:
        """Generate OAuth authorization URL with CSRF protection"""
        try:
            # Normalize shop domain
            if not shop_domain.endswith('.myshopify.com'):
                shop_domain = f"{shop_domain}.myshopify.com"
            
            # Generate CSRF state token if not provided
            if not state:
                state = secrets.token_hex(16)
            
            # Use provided scopes or defaults
            scopes_list = scopes or self.default_scopes
            
            params = {
                'client_id': self.client_id,
                'scope': ','.join(scopes_list),
                'redirect_uri': self.redirect_uri,
                'state': state,
                'grant_options[]': 'per-user'  # Request online access token
            }
            
            auth_url = f"https://{shop_domain}/admin/oauth/authorize?{urlencode(params)}"
            
            logger.info(f"Generated Shopify auth URL for shop: {shop_domain}")
            return auth_url, state
            
        except Exception as e:
            logger.error(f"Error generating Shopify auth URL: {e}")
            raise ShopifyAPIException(f"Failed to generate authorization URL: {str(e)}")
    
    async def exchange_code_for_token(self, shop_domain: str, code: str, state: str = None) -> Dict:
        """Exchange authorization code for access token"""
        try:
            # Normalize shop domain
            if not shop_domain.endswith('.myshopify.com'):
                shop_domain = f"{shop_domain}.myshopify.com"
            
            token_url = f"https://{shop_domain}/admin/oauth/access_token"
            
            payload = {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': code
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(token_url, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"Shopify token exchange failed: {response.status_code} - {response.text}")
                    raise ShopifyAPIException(f"Token exchange failed with status {response.status_code}")
                
                token_data = response.json()
                
                # Validate required fields
                if 'access_token' not in token_data:
                    raise ShopifyAPIException("Access token not found in response")
                
                logger.info(f"Successfully exchanged code for token: {shop_domain}")
                
                return {
                    'access_token': token_data['access_token'],
                    'scope': token_data.get('scope', ''),
                    'expires_in': token_data.get('expires_in'),
                    'associated_user_scope': token_data.get('associated_user_scope'),
                    'associated_user': token_data.get('associated_user', {}),
                    'shop_domain': shop_domain
                }
                
        except httpx.RequestError as e:
            logger.error(f"Network error during Shopify token exchange: {e}")
            raise ShopifyAPIException(f"Network error during token exchange: {str(e)}")
        except Exception as e:
            logger.error(f"Error exchanging Shopify code for token: {e}")
            raise ShopifyAPIException(f"Token exchange failed: {str(e)}")
    
    async def verify_token(self, shop_domain: str, access_token: str) -> bool:
        """Verify access token is valid by making a test API call"""
        try:
            if not shop_domain.endswith('.myshopify.com'):
                shop_domain = f"{shop_domain}.myshopify.com"
            
            test_url = f"https://{shop_domain}/admin/api/{settings.shopify_api_version}/shop.json"
            
            headers = {
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(test_url, headers=headers)
                
                if response.status_code == 200:
                    logger.info(f"Shopify token verified successfully for: {shop_domain}")
                    return True
                elif response.status_code == 401:
                    logger.warning(f"Shopify token invalid for: {shop_domain}")
                    return False
                else:
                    logger.error(f"Unexpected response during token verification: {response.status_code}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error verifying Shopify token: {e}")
            return False
    
    async def get_shop_info(self, shop_domain: str, access_token: str) -> Optional[Dict]:
        """Get shop information using access token"""
        try:
            if not shop_domain.endswith('.myshopify.com'):
                shop_domain = f"{shop_domain}.myshopify.com"
            
            shop_url = f"https://{shop_domain}/admin/api/{settings.shopify_api_version}/shop.json"
            
            headers = {
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(shop_url, headers=headers)
                
                if response.status_code == 200:
                    shop_data = response.json()
                    return shop_data.get('shop', {})
                else:
                    logger.error(f"Failed to get shop info: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting shop info: {e}")
            return None
    
    def generate_webhook_verification_token(self) -> str:
        """Generate a secure webhook verification token"""
        return secrets.token_hex(32)
    
    async def create_webhook(self, shop_domain: str, access_token: str, topic: str, address: str, verification_token: str = None) -> Optional[Dict]:
        """Create a webhook in Shopify"""
        try:
            if not shop_domain.endswith('.myshopify.com'):
                shop_domain = f"{shop_domain}.myshopify.com"
            
            webhook_url = f"https://{shop_domain}/admin/api/{settings.shopify_api_version}/webhooks.json"
            
            headers = {
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json'
            }
            
            webhook_data = {
                'webhook': {
                    'topic': topic,
                    'address': address,
                    'format': 'json'
                }
            }
            
            if verification_token:
                webhook_data['webhook']['api_client_id'] = verification_token
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(webhook_url, headers=headers, json=webhook_data)
                
                if response.status_code == 201:
                    webhook_info = response.json()
                    logger.info(f"Created webhook for topic {topic} on {shop_domain}")
                    return webhook_info.get('webhook', {})
                else:
                    logger.error(f"Failed to create webhook: {response.status_code} - {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error creating webhook: {e}")
            return None
    
    async def setup_required_webhooks(self, shop_domain: str, access_token: str, webhook_base_url: str) -> Dict[str, bool]:
        """Set up all required webhooks for the e-commerce bot"""
        required_webhooks = [
            'orders/create',
            'orders/updated', 
            'orders/paid',
            'orders/cancelled',
            'orders/fulfilled',
            'customers/create',
            'customers/update',
            'app/uninstalled'
        ]
        
        results = {}
        verification_token = self.generate_webhook_verification_token()
        
        for topic in required_webhooks:
            webhook_url = f"{webhook_base_url}/shopify/webhooks/{topic.replace('/', '_')}"
            webhook_info = await self.create_webhook(
                shop_domain, access_token, topic, webhook_url, verification_token
            )
            results[topic] = webhook_info is not None
        
        return results


# Global Shopify OAuth instance
shopify_oauth = ShopifyOAuth()