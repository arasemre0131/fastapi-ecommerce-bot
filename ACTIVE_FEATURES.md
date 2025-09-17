# 🎯 Şu Anda Test Edebileceğiniz Aktif Fonksiyonlar

## 🚀 Hemen Test Edilebilir Endpoints

### 1. **Temel API Endpoints**
```bash
GET  /                    # Ana sayfa bilgisi
GET  /health             # Sistem durumu
GET  /docs               # Swagger API dokümantasyonu  
GET  /redoc              # ReDoc API dokümantasyonu
```

### 2. **Authentication Endpoints**
```bash
POST /api/v1/auth/register      # Kullanıcı kaydı
POST /api/v1/auth/login         # Giriş yapma
POST /api/v1/auth/refresh       # Token yenileme
GET  /api/v1/auth/me           # Kullanıcı bilgisi
PUT  /api/v1/auth/me           # Kullanıcı güncelleme
POST /api/v1/auth/logout        # Çıkış yapma
POST /api/v1/auth/change-password # Şifre değiştirme
```

### 3. **API Key Management**
```bash
POST /api/v1/auth/api-keys      # API key oluşturma
GET  /api/v1/auth/api-keys      # API key listesi
DELETE /api/v1/auth/api-keys/{id} # API key silme
```

### 4. **Shopify Integration** (Webhook'lar)
```bash
GET  /api/v1/shopify/auth/install     # Shopify kurulum başlatma
GET  /api/v1/shopify/auth/callback    # OAuth callback
POST /api/v1/shopify/webhooks/*       # Shopify webhook'ları
```

## 🧪 Hızlı Test için

### **Yöntem 1: Test Script ile**
```bash
cd ~/Desktop/fastapi-ecommerce-bot
python test_api.py
```

### **Yöntem 2: Manuel Başlatma**
```bash
cd ~/Desktop/fastapi-ecommerce-bot

# Minimal setup
pip install fastapi uvicorn httpx loguru pydantic pydantic-settings
cp .env.example .env

# Sunucu başlat
uvicorn src.main:app --reload

# Tarayıcıda aç
open http://localhost:8000/docs
```

### **Yöntem 3: Docker ile**
```bash
cd ~/Desktop/fastapi-ecommerce-bot
docker-compose up -d
open http://localhost:8000/docs
```

## ✅ Çalışan Özellikler

### **🔐 Security Features**
- ✅ JWT token authentication
- ✅ API key authentication  
- ✅ Rate limiting middleware
- ✅ CORS protection
- ✅ Security headers
- ✅ Request/response logging
- ✅ Error handling

### **📊 Monitoring**
- ✅ Health check endpoint
- ✅ Structured logging
- ✅ Correlation ID tracking
- ✅ Request timing

### **🏗️ Infrastructure**
- ✅ FastAPI application
- ✅ Async SQLAlchemy ORM
- ✅ Alembic migrations
- ✅ Redis caching (Docker'da)
- ✅ Background queues
- ✅ Exception handling

## ⚠️ Test İçin Gerekli Ayarlar

### **Database**
- 🔧 PostgreSQL (Docker) veya SQLite (test)
- 🔧 Migration'lar çalıştırılmalı

### **External APIs**
- 🔧 OpenAI API key (AI chat için)
- 🔧 Shopify app credentials (Shopify entegrasyonu için)
- 🔧 WhatsApp Cloud API (mesajlaşma için)

## 🎯 Test Senaryoları

### **1. API Dokümantasyonu**
```bash
curl http://localhost:8000/
curl http://localhost:8000/health
```

### **2. Kullanıcı Kaydı & Giriş**
```bash
# Kullanıcı kaydı
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "Test123456",
    "full_name": "Test User"
  }'

# Giriş
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test@example.com&password=Test123456"
```

### **3. Authenticated Endpoints**
```bash
# Token ile kullanıcı bilgisi
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## 🚧 Geliştirilmekte Olan Özellikler

- 🔄 WhatsApp mesajlaşma handlers
- 🔄 WooCommerce router'ları  
- 🔄 OpenAI chat endpoints
- 🔄 PII masking implementation
- 🔄 GDPR compliance endpoints
- 🔄 Advanced monitoring

## 💡 Önerilen Test Sırası

1. **Sunucuyu başlatın** → `python test_api.py`
2. **API docs'u açın** → `http://localhost:8000/docs`
3. **Health check** → Test edin
4. **Kullanıcı kaydı** → Yeni hesap oluşturun
5. **Login** → JWT token alın
6. **Protected endpoints** → Token ile test edin
7. **API key oluşturun** → Alternative auth test edin

**En kolay başlangıç: Swagger UI kullanarak tüm endpoint'leri test edebilirsiniz!** 🎉