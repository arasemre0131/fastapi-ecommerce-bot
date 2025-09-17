# 🚀 GitHub'a Push Etme Komutları

GitHub'da repository oluşturduktan sonra şu komutları terminal'de çalıştırın:

```bash
# Projeye gidin
cd ~/Desktop/fastapi-ecommerce-bot

# GitHub remote ekleyin (YOUR_USERNAME'i kendi kullanıcı adınızla değiştirin)
git remote add origin https://github.com/YOUR_USERNAME/fastapi-ecommerce-bot.git

# Main branch olarak ayarlayın
git branch -M main

# GitHub'a push edin
git push -u origin main
```

## 🔧 Alternatif: GitHub CLI ile

Eğer GitHub CLI yüklüyse:

```bash
# GitHub CLI yükleyin (Mac)
brew install gh

# Login olun
gh auth login

# Repo oluşturun ve push edin
gh repo create fastapi-ecommerce-bot --public --push --source=.
```

## ✅ Başarılı Push Sonrası

Repo URL'iniz: `https://github.com/YOUR_USERNAME/fastapi-ecommerce-bot`

### İlk Kurulum:
```bash
git clone https://github.com/YOUR_USERNAME/fastapi-ecommerce-bot.git
cd fastapi-ecommerce-bot
cp .env.example .env
# .env dosyasını düzenleyin
docker-compose up -d
```