#!/usr/bin/env python3
"""
🧪 FastAPI E-Commerce Bot Test Script
Bu script, Docker olmadan API'yi test etmenizi sağlar.
"""
import asyncio
import httpx
import uvicorn
import subprocess
import sys
import os
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_dependencies():
    """Check if required packages are installed"""
    required_packages = [
        "fastapi", "uvicorn", "httpx", "loguru", 
        "pydantic", "pydantic-settings"
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing.append(package)
    
    if missing:
        print(f"❌ Eksik paketler: {', '.join(missing)}")
        print("💡 Kurulum için: pip install " + " ".join(missing))
        return False
    
    print("✅ Tüm temel paketler mevcut")
    return True

def create_minimal_env():
    """Create minimal .env file for testing"""
    env_content = """# Minimal test configuration
DEBUG=true
ENVIRONMENT=development
SECRET_KEY=test-secret-key-for-development-only
PORT=8000
LOG_LEVEL=INFO

# Database (SQLite for testing)
DATABASE_URL=sqlite:///./test.db

# Redis (disabled for testing)
REDIS_URL=redis://localhost:6379/0

# API Keys (mock values for testing)
OPENAI_API_KEY=test-key
SHOPIFY_CLIENT_ID=test-client-id
SHOPIFY_CLIENT_SECRET=test-client-secret
WHATSAPP_ACCESS_TOKEN=test-token
"""
    
    env_path = Path(".env")
    if not env_path.exists():
        with open(env_path, "w") as f:
            f.write(env_content)
        print("✅ Test .env dosyası oluşturuldu")
    else:
        print("📋 .env dosyası zaten mevcut")

async def test_endpoints():
    """Test API endpoints"""
    base_url = "http://localhost:8000"
    
    test_cases = [
        ("GET", "/", "Ana sayfa"),
        ("GET", "/health", "Health check"),
        ("GET", "/docs", "API dokümantasyonu"),
        ("GET", "/api/v1/auth/me", "Auth endpoint (401 beklenir)"),
    ]
    
    print("\n🧪 API Endpoint Testleri:")
    print("-" * 50)
    
    async with httpx.AsyncClient() as client:
        for method, endpoint, description in test_cases:
            try:
                response = await client.request(method, f"{base_url}{endpoint}")
                status_emoji = "✅" if response.status_code < 400 else "⚠️" 
                print(f"{status_emoji} {method} {endpoint} -> {response.status_code} ({description})")
                
                if endpoint == "/":
                    print(f"   📝 Response: {response.json()}")
                elif endpoint == "/health":
                    health = response.json()
                    print(f"   🏥 Status: {health.get('status', 'unknown')}")
                    
            except Exception as e:
                print(f"❌ {method} {endpoint} -> ERROR: {str(e)}")

def run_server():
    """Run FastAPI server"""
    print("🚀 FastAPI sunucusu başlatılıyor...")
    print("📍 URL: http://localhost:8000")
    print("📚 Docs: http://localhost:8000/docs")
    print("🔄 Ctrl+C ile durdurun")
    print("-" * 50)
    
    try:
        # Import here to avoid early import issues
        from src.main import app
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except ImportError as e:
        print(f"❌ Import hatası: {e}")
        print("💡 Önce bağımlılıkları yükleyin: pip install -r requirements/base.txt")
    except Exception as e:
        print(f"❌ Sunucu hatası: {e}")

async def main():
    """Main test function"""
    print("🤖 FastAPI E-Commerce Bot Test Aracı")
    print("=" * 50)
    
    # Check dependencies
    if not check_dependencies():
        return
    
    # Create test environment
    create_minimal_env()
    
    print("\n📋 Mevcut Özellikler:")
    print("✅ FastAPI temel yapısı")
    print("✅ Health check endpoint")
    print("✅ Authentication sistemi (kısmi)")
    print("✅ Shopify entegrasyonu (kısmi)")
    print("✅ Security middleware")
    print("✅ Error handling")
    print("⚠️  Database: Test için SQLite")
    print("⚠️  Redis: Devre dışı")
    print("⚠️  OpenAI: Mock API key")
    
    choice = input("\n🚀 Sunucuyu başlatmak istiyor musunuz? (y/n): ")
    
    if choice.lower() in ['y', 'yes', 'evet']:
        # Run server in background for testing
        print("\n🏃‍♂️ Sunucu başlatılıyor...")
        run_server()
    else:
        print("📝 Manuel başlatma için: python test_api.py")
        print("📚 Veya uvicorn src.main:app --reload")

if __name__ == "__main__":
    asyncio.run(main())