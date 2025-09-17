# E-Commerce Support Bot MVP

A production-ready e-commerce customer support bot built with FastAPI, featuring AI-powered responses, multi-platform integrations (Shopify, WooCommerce, WhatsApp), and enterprise-grade security.

## 🚀 Features

### Core Features
- **AI-Powered Support**: OpenAI GPT-4 integration with function calling for intelligent customer service
- **Multi-Platform Integration**: Shopify, WooCommerce, and WhatsApp Cloud API support
- **Real-time Processing**: Webhook handling for order updates, customer messages, and platform events
- **Secure Authentication**: JWT tokens, API keys, and OAuth 2.0 with rate limiting
- **Production-Ready**: Docker containerization, CI/CD pipeline, and monitoring

### Platform Integrations
- **Shopify**: OAuth 2.0 authentication, webhook handling, order management
- **WooCommerce**: REST API integration, order tracking, customer management
- **WhatsApp Business**: Cloud API integration with 24-hour messaging window support
- **OpenAI**: Function calling for order status, returns, product search

### Security & Compliance
- **GDPR Compliance**: Data retention, right to deletion, audit logging
- **PII Protection**: Automatic masking of sensitive information
- **Rate Limiting**: API and webhook rate limiting with Redis
- **Security Headers**: CORS, CSRF protection, security middleware

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL 13+
- Redis 6+
- Docker & Docker Compose
- API Keys for:
  - OpenAI GPT-4
  - Shopify App (for merchants)
  - WhatsApp Cloud API
  - WooCommerce (per merchant)

## 🛠️ Installation & Setup

### 1. Clone Repository
```bash
git clone <repository-url>
cd fastapi-ecommerce-bot
```

### 2. Environment Setup
```bash
# Copy environment template
cp .env.example .env

# Edit environment variables
nano .env
```

Required environment variables:
```env
# Database
DATABASE_URL=postgresql+asyncpg://username:password@localhost:5432/ecommerce_bot

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_QUEUE_URL=redis://localhost:6379/1

# Security
SECRET_KEY=your-secret-key-here

# OpenAI
OPENAI_API_KEY=your-openai-api-key

# Shopify
SHOPIFY_CLIENT_ID=your-shopify-client-id
SHOPIFY_CLIENT_SECRET=your-shopify-client-secret

# WhatsApp
WHATSAPP_ACCESS_TOKEN=your-whatsapp-access-token
WHATSAPP_VERIFY_TOKEN=your-whatsapp-verify-token
```

### 3. Development Setup

#### Using Docker Compose (Recommended)
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f app

# Run migrations
docker-compose exec app alembic upgrade head
```

#### Manual Setup
```bash
# Install dependencies
pip install -r requirements/dev.txt

# Start PostgreSQL and Redis
# (Install and configure manually or use Docker)

# Run migrations
alembic upgrade head

# Start development server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Database Migration
```bash
# Create new migration
alembic revision --autogenerate -m "Description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1
```

## 🔧 Configuration

### Shopify Integration Setup
1. Create Shopify App in Partner Dashboard
2. Configure OAuth redirect URL: `https://yourapp.com/api/v1/shopify/auth/callback`
3. Set webhook endpoints for order events
4. Add required scopes: `read_orders`, `read_customers`, `write_orders`

### WhatsApp Cloud API Setup
1. Create Meta Business Account
2. Set up WhatsApp Business API
3. Configure webhook URL: `https://yourapp.com/api/v1/whatsapp/webhook`
4. Verify webhook with your verify token

### WooCommerce Setup
1. Install WooCommerce REST API plugin
2. Generate consumer key/secret for each merchant
3. Configure webhook endpoints in WooCommerce admin

## 🚀 Deployment

### Fly.io Deployment
```bash
# Install Fly CLI
curl -L https://fly.io/install.sh | sh

# Login and deploy
fly auth login
fly deploy
```

### Render Deployment
1. Connect GitHub repository to Render
2. Configure environment variables
3. Deploy automatically on git push

### Docker Deployment
```bash
# Build image
docker build -t ecommerce-bot .

# Run container
docker run -p 8000:8000 --env-file .env ecommerce-bot
```

## 📚 API Documentation

Once running, visit:
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### Key Endpoints

#### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login
- `POST /api/v1/auth/refresh` - Refresh tokens
- `GET /api/v1/auth/me` - Get current user

#### Shopify Integration
- `GET /api/v1/shopify/auth/install` - Start Shopify installation
- `GET /api/v1/shopify/auth/callback` - OAuth callback
- `POST /api/v1/shopify/webhooks/*` - Webhook endpoints

#### WhatsApp Integration
- `POST /api/v1/whatsapp/webhook` - Message webhook
- `GET /api/v1/whatsapp/webhook` - Webhook verification

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run linting
flake8 src
black --check src
isort --check-only src
```

## 📊 Monitoring & Logging

### Health Checks
- **Application**: `/health` endpoint with database/Redis checks
- **Docker**: Built-in health check configuration
- **Kubernetes**: Liveness and readiness probes

### Logging
- **Structured Logging**: JSON format with correlation IDs
- **Log Levels**: Configurable via environment
- **Request Tracking**: Middleware for request/response logging

### Metrics
- **Application Metrics**: Custom metrics via Prometheus
- **System Metrics**: Container and infrastructure monitoring
- **Business Metrics**: Order processing, response times

## 🔐 Security Best Practices

### Authentication & Authorization
- JWT tokens with secure refresh mechanism
- API key authentication for webhooks
- Rate limiting per user/API key
- Account lockout after failed attempts

### Data Protection
- PII masking in logs and responses
- GDPR compliance with data retention policies
- Encrypted sensitive data storage
- Audit logging for compliance

### Infrastructure Security
- Security headers middleware
- CORS configuration
- HTTPS enforcement
- Container security scanning

## 🐛 Troubleshooting

### Common Issues

#### Database Connection Errors
```bash
# Check database connectivity
docker-compose exec app python -c "from src.core.database import check_database_connection; import asyncio; print(asyncio.run(check_database_connection()))"
```

#### Redis Connection Issues
```bash
# Test Redis connection
docker-compose exec redis redis-cli ping
```

#### Webhook Verification Failures
1. Verify webhook secrets match
2. Check HTTPS configuration
3. Validate webhook URL accessibility

#### Rate Limiting Issues
```bash
# Check Redis rate limit keys
docker-compose exec redis redis-cli keys "rate_limit:*"
```

### Debug Mode
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
export DEBUG=true

# Run with debug
uvicorn src.main:app --reload --log-level debug
```

## 📈 Performance Optimization

### Database Optimization
- Indexed queries for common lookups
- Connection pooling with optimal settings
- Query optimization with SQLAlchemy

### Caching Strategy
- Redis caching for frequently accessed data
- Cache invalidation on data updates
- TTL-based cache expiration

### Background Processing
- Async queue processing for webhooks
- Celery workers for heavy tasks
- Rate limiting to prevent overload

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

### Code Standards
- Follow PEP 8 style guide
- Add type hints to all functions
- Write tests for new features
- Update documentation

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

For support and questions:
- Create an issue in GitHub
- Check existing documentation
- Review troubleshooting guide

## 🗺️ Roadmap

### Phase 1 (Current)
- ✅ Core FastAPI application
- ✅ Shopify integration
- ✅ WhatsApp integration
- ✅ OpenAI function calling

### Phase 2 (Next)
- [ ] Advanced AI conversation flows
- [ ] Multi-language support
- [ ] Analytics dashboard
- [ ] A/B testing framework

### Phase 3 (Future)
- [ ] Voice call integration
- [ ] Video chat support
- [ ] Machine learning optimization
- [ ] Enterprise features