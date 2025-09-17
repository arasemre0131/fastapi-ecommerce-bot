from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    # App Configuration
    app_name: str = "E-Commerce Support Bot"
    version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False
    
    # API Configuration
    api_v1_prefix: str = "/api/v1"
    port: int = 8000
    host: str = "0.0.0.0"
    
    # Security
    secret_key: str
    access_token_expire_minutes: int = 30
    algorithm: str = "HS256"
    
    # Database
    database_url: str
    database_pool_size: int = 20
    database_max_overflow: int = 30
    database_pool_timeout: int = 30
    database_pool_recycle: int = 3600
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_queue_url: str = "redis://localhost:6379/1"
    
    # External APIs
    openai_api_key: str
    openai_model: str = "gpt-4o"
    openai_max_tokens: int = 1000
    openai_temperature: float = 0.1
    
    # Shopify
    shopify_client_id: Optional[str] = None
    shopify_client_secret: Optional[str] = None
    shopify_webhook_secret: Optional[str] = None
    shopify_api_version: str = "2023-10"
    
    # WooCommerce
    woocommerce_consumer_key: Optional[str] = None
    woocommerce_consumer_secret: Optional[str] = None
    
    # WhatsApp
    whatsapp_access_token: Optional[str] = None
    whatsapp_verify_token: Optional[str] = None
    whatsapp_phone_number_id: Optional[str] = None
    whatsapp_business_account_id: Optional[str] = None
    
    # Rate Limiting
    rate_limit_calls: int = 100
    rate_limit_period: int = 60
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}"
    
    # GDPR & Privacy
    data_retention_days: int = 730  # 2 years
    pii_masking_enabled: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()