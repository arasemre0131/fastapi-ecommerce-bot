# 🚀 GitHub Repository Kurulum Rehberi

## Adım 1: GitHub'da Repository Oluşturun

1. https://github.com/arasemre0131 adresine gidin
2. **"New"** veya **"+"** butonuna tıklayın
3. **"New repository"** seçin

### Repository Bilgileri:
- **Repository name:** `fastapi-ecommerce-bot`
- **Description:** `🤖 Production-ready FastAPI e-commerce support bot with AI, Shopify, WooCommerce & WhatsApp integrations`
- **Visibility:** ✅ **Public** 
- **Initialize repository:** ❌ **BOŞ BIRAKIN** (kod zaten hazır)

## Adım 2: Terminal Komutları

Repository oluşturduktan sonra terminal'de:

```bash
cd ~/Desktop/fastapi-ecommerce-bot

# Remote zaten eklendi
git remote -v

# Push edin
git push -u origin main
```

## Adım 3: Sonuç

✅ Repository URL: https://github.com/arasemre0131/fastapi-ecommerce-bot

## ⚠️ İlk Push Problemi Yaşarsanız:

```bash
# Authentication gerekirse
git config --global user.name "arasemre0131"
git config --global user.email "your_email@example.com"

# Personal Access Token kullanın (GitHub > Settings > Developer settings > Personal access tokens)
```