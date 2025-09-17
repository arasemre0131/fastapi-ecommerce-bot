from sqlalchemy import (
    String, Text, Integer, BigInteger, Boolean, DateTime, 
    ForeignKey, Index, CheckConstraint, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from typing import Optional, List
import uuid

from .database import Base


class Merchant(Base):
    __tablename__ = "merchants"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), default=lambda: str(uuid.uuid4()), unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    website: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Platform settings
    platform_type: Mapped[str] = mapped_column(String(50), nullable=False)  # shopify, woocommerce
    platform_domain: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Shopify specific
    shopify_shop_domain: Mapped[Optional[str]] = mapped_column(String(255))
    shopify_access_token: Mapped[Optional[str]] = mapped_column(Text)
    shopify_webhook_secret: Mapped[Optional[str]] = mapped_column(String(255))
    
    # WooCommerce specific
    woocommerce_url: Mapped[Optional[str]] = mapped_column(String(255))
    woocommerce_consumer_key: Mapped[Optional[str]] = mapped_column(String(255))
    woocommerce_consumer_secret: Mapped[Optional[str]] = mapped_column(Text)
    
    # WhatsApp settings
    whatsapp_phone_number_id: Mapped[Optional[str]] = mapped_column(String(255))
    whatsapp_access_token: Mapped[Optional[str]] = mapped_column(Text)
    whatsapp_business_account_id: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Status and settings
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscription_plan: Mapped[str] = mapped_column(String(50), default="basic")
    ai_settings: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Relationships
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="merchant")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="merchant")
    
    __table_args__ = (
        Index("ix_merchants_platform_domain", "platform_type", "platform_domain"),
        Index("ix_merchants_active", "is_active", "created_at"),
        CheckConstraint("platform_type IN ('shopify', 'woocommerce')", name="ck_merchants_platform_type"),
    )


class Customer(Base):
    __tablename__ = "customers"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    
    # Customer identifiers
    external_id: Mapped[Optional[str]] = mapped_column(String(255))  # Shopify/WooCommerce customer ID
    whatsapp_id: Mapped[Optional[str]] = mapped_column(String(255))  # WhatsApp user ID
    phone_number: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Customer details
    first_name: Mapped[Optional[str]] = mapped_column(String(100))
    last_name: Mapped[Optional[str]] = mapped_column(String(100))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Preferences
    language: Mapped[str] = mapped_column(String(10), default="en")
    timezone: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Privacy settings
    consent_marketing: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_data_processing: Mapped[bool] = mapped_column(Boolean, default=True)
    data_retention_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="customer")
    
    __table_args__ = (
        Index("ix_customers_merchant_external", "merchant_id", "external_id"),
        Index("ix_customers_whatsapp", "whatsapp_id"),
        Index("ix_customers_phone", "phone_number"),
        Index("ix_customers_email", "email"),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"))
    
    # Conversation details
    status: Mapped[str] = mapped_column(String(50), default="active")  # active, closed, transferred
    channel: Mapped[str] = mapped_column(String(50), default="whatsapp")  # whatsapp, web, api
    
    # Context and state
    context: Mapped[Optional[dict]] = mapped_column(JSON)  # Conversation context for AI
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Agent assignment
    assigned_agent_id: Mapped[Optional[int]] = mapped_column(BigInteger)  # Future: human agents
    escalated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="conversations")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation")
    
    __table_args__ = (
        Index("ix_conversations_merchant_status_updated", "merchant_id", "status", "updated_at"),
        Index("ix_conversations_active", "merchant_id", "updated_at", postgresql_where="status = 'active'"),
        Index("ix_conversations_customer", "customer_id", "created_at"),
        CheckConstraint("status IN ('active', 'closed', 'transferred')", name="ck_conversations_status"),
        CheckConstraint("channel IN ('whatsapp', 'web', 'api')", name="ck_conversations_channel"),
    )


class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    
    # Message details
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), default="text")  # text, image, audio, document
    
    # Sender information
    sender_type: Mapped[str] = mapped_column(String(50), nullable=False)  # customer, bot, agent
    sender_id: Mapped[Optional[str]] = mapped_column(String(255))  # WhatsApp ID or agent ID
    
    # Message metadata
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255))  # WhatsApp message ID
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # inbound, outbound
    
    # AI processing
    intent: Mapped[Optional[str]] = mapped_column(String(100))  # Detected intent
    entities: Mapped[Optional[dict]] = mapped_column(JSON)  # Extracted entities
    confidence_score: Mapped[Optional[float]] = mapped_column()
    
    # Status tracking
    status: Mapped[str] = mapped_column(String(50), default="sent")  # sent, delivered, read, failed
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_external_id", "external_message_id"),
        Index("ix_messages_sender", "sender_type", "sender_id"),
        CheckConstraint("sender_type IN ('customer', 'bot', 'agent')", name="ck_messages_sender_type"),
        CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        CheckConstraint("content_type IN ('text', 'image', 'audio', 'document', 'interactive')", name="ck_messages_content_type"),
    )


class Order(Base):
    __tablename__ = "orders"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("customers.id", ondelete="SET NULL"))
    
    # Order identifiers
    external_order_id: Mapped[str] = mapped_column(String(255), nullable=False)  # Shopify/WooCommerce order ID
    order_number: Mapped[str] = mapped_column(String(255), nullable=False)  # Human-readable order number
    
    # Order details
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    financial_status: Mapped[Optional[str]] = mapped_column(String(50))
    fulfillment_status: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Amounts
    total_amount: Mapped[Optional[float]] = mapped_column()
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    
    # Customer information (denormalized for quick access)
    customer_email: Mapped[Optional[str]] = mapped_column(String(255))
    customer_phone: Mapped[Optional[str]] = mapped_column(String(50))
    customer_name: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Shipping
    shipping_address: Mapped[Optional[dict]] = mapped_column(JSON)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(255))
    tracking_url: Mapped[Optional[str]] = mapped_column(String(500))
    
    # Order data (full order details from platform)
    order_data: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Timestamps
    order_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="orders")
    customer: Mapped[Optional["Customer"]] = relationship("Customer")
    
    __table_args__ = (
        Index("ix_orders_merchant_external", "merchant_id", "external_order_id"),
        Index("ix_orders_number", "order_number"),
        Index("ix_orders_customer_email", "customer_email"),
        Index("ix_orders_status", "status", "created_at"),
        Index("ix_orders_tracking", "tracking_number"),
    )


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merchant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    
    # Event details
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # shopify, woocommerce, whatsapp
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_id: Mapped[Optional[str]] = mapped_column(String(255))  # External event ID
    
    # Processing status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, processing, completed, failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    
    # Event data
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant")
    
    __table_args__ = (
        Index("ix_webhook_events_merchant_status", "merchant_id", "status", "created_at"),
        Index("ix_webhook_events_source_type", "source", "event_type"),
        Index("ix_webhook_events_processing", "status", "attempts", "created_at"),
        CheckConstraint("source IN ('shopify', 'woocommerce', 'whatsapp')", name="ck_webhook_events_source"),
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="ck_webhook_events_status"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merchant_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("merchants.id", ondelete="SET NULL"))
    
    # Event details
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)  # data_access, data_deletion, etc.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # customer, conversation, order
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # User context
    user_id: Mapped[Optional[str]] = mapped_column(String(255))
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    
    # Change details
    changes: Mapped[Optional[dict]] = mapped_column(JSON)
    metadata: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # GDPR compliance
    legal_basis: Mapped[Optional[str]] = mapped_column(String(100))
    retention_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    __table_args__ = (
        Index("ix_audit_logs_merchant_event", "merchant_id", "event_type", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_retention", "retention_until"),
    )