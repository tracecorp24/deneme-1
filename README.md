# VFS Global Bulgaristan Vize Randevu Botu

Türkiye &rarr; Bulgaristan VFS Global vize başvuru portalı (`https://visa.vfsglobal.com/tur/en/bgr/`) için geliştirilmiş, ban korumalı ve iki katmanlı hibrit randevu tespit ve rezervasyon otomasyon sistemi.

> **Modül Mimarisi:** `core/` modülü yalnızca Aşama 1 teşhis ve tarayıcı doğrulama testleri içindir; 7/24 kesintisiz üretim kodu ve rezervasyon motoru tamamen `bot/` modülü altındadır.

---

## 🚀 Özellikler

### 1. İki Katmanlı Mimari (Plan v2)
* **Katman 0 (Public Sweep — Sıfır Hesap Riski)**:
  - `POST /appointment/centerwithearliestslot` çağrısı ile hesap girişi yapmadan, OTP harcamadan ve ban riski olmadan tüm merkezler (İstanbul, Ankara, Edirne, Bursa, İzmir) ve kategoriler için en erken randevu tarihlerini 5-8 dakika aralıklarla yoklar.
  - Tarih aralığı (`tarih_baslangic`, `tarih_bitis`) ve başvuru merkezi tercihi eşleştirmesi.
  - Hash tabanlı global ve başvuran bazlı mükerrer bildirim engelleme (deduplication).
* **Katman 1 (Hedefli Doğrulama & Otomatik Rezervasyon)**:
  - Yalnızca uygun tarihli bir slot tespit edildiğinde veya kullanıcı talep ettiğinde devreye girer.
  - Eşzamanlı rezervasyon kilidi (`booking_lock`) ve işlem idempotensi (`submitted_at`).
  - Oturum koruması: Geçerli oturum varsa tekrar login olmaz (24 saatlik 429202 kilitlenmesini önler).
  - JWT `exp` zaman denetimi ile bayat oturumların otomatik yenilenmesi.
  - Hedefli IMAP e-posta OTP köprüsü ile 6 haneli doğrulama kodunu otomatik alma.
  - `<500 ms` içinde `POST /appointment/bookappointment` isteği gönderme.

### 2. İnsansı Anti-Detect & Cloudflare Turnstile Çözümü (Aşama 1)
* **Patchright + Resmi Google Chrome**: CDP sızıntılarını ve tarayıcı otomasyon bayraklarını temizler.
* **Kalıcı Profil (Persistent Context)**: Kullanıcı çerezlerini ve oturum geçmişini korur.
* **İnsansı Davranış Modelleri**: Kübik Bézier fare eğrileri, mikrotitremeler (micro-tremor), doğal sayfa kaydırma ve değişken zamanlamalar.

### 3. Modern Web Kontrol Paneli
* **Cam Efektli (Glassmorphism) Arayüz**: Outfit & Inter tipografisi, koyu tema.
* **4 KPI Metrik Kartı**: Aktif Başvuranlar, Tespit Edilen Slotlar, Alınan Randevular, Son Tarama Zamanı.
* **Excel & SQLite İki Yönlü Eşitleme**: 23 sütunlu başvuran listesini yönetme ve canlı durum takibi (`PENDING`, `SLOT_FOUND`, `BOOKED`, `LOCKED_24H`).
* **Canlı Konsol & Ekran Görüntüsü**: Bot loglarını ve Cloudflare Turnstile doğrulama kanıtlarını canlı izleme.
* **Telegram Callback Desteği**: `book:{id}` ve `skip:{id}` butonları için çift yönlü webhook işleyici.

---

## 🛠️ Kurulum

### Gereksinimler
* Python 3.10+
* **Google Chrome**: Sisteminizde resmi Google Chrome kurulu olmalıdır (Patchright otomatik olarak Chrome ikilisini kullanır; harici chromium indirilmesine gerek yoktur).
* Git

```bash
# 1. Depoyu klonlayın
git clone https://github.com/tracecorp24/deneme-1.git
cd deneme-1

# 2. Bağımlılıkları yükleyin
pip install -r requirements.txt
```

---

## 🔐 Yapılandırma (`.env` & `config.yaml`)

Tüm hassas kimlik bilgileri, API anahtarları ve ortama özel sırlar `.env` dosyasında tutulur; `config.yaml` dosyası yalnızca varsayılan sistem sabitlerini içerir.

### 1. `.env` Dosyası Oluşturma
Örnek şablondan kendi `.env` dosyanızı kopyalayın:
```bash
copy .env.example .env
```

`.env` içerisindeki anahtarları doldurun:
```env
# VFS Global Lift API Yetki Belirteci (scripts/find_token.py ile otomatik bulunabilir)
VFS_X_TOKEN=

# ISP / Residential Proxy Havuzu (Virgülle ayrılmış: user:pass@ip:port veya ip:port)
VFS_PROXIES=

# Tarayıcı Görünürlüğü (True: Arka plan, False: Görünür pencereli)
VFS_HEADLESS=false

# Telegram Bildirimleri & Callback
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

# Katman 1 Otomatik Rezervasyon (true / false)
AUTO_BOOK=false

# Excel Başvuran Dosyası
EXCEL_PATH=data/basvuranlar.xlsx
```

### 2. Token Bulma Aracı
VFS x-auth-token belirtecinizi tek komutla otomatik almak için:
```bash
python scripts/find_token.py
```
Belirteç bulunduğunda doğrudan `token.txt` ve `.env` dosyanıza işlenir.

---

## 🏃‍♂️ Çalıştırma

### 1. Web Kontrol Paneli (Tavsiye Edilen)
```bash
# Windows kolay başlatıcı:
start.bat

# veya terminal üzerinden:
python web_app.py
```
Tarayıcınızdan `http://localhost:5000` adresine gidin. Arayüzden:
- Başvuranlar Excel dosyasını yükleyebilirsiniz,
- Canlı Bot'u başlatıp durdurabilirsiniz,
- Tek tıkla "Anlık Slot Taraması (Katman 0)" ve "Manuel Rezervasyon (Katman 1)" yapabilirsiniz.

### 2. Konsol Üzerinden Canlı Bot
```bash
python -m bot.main
```

### 3. Aşama 1 Tarayıcı & Turnstile Teşhis Testi
```bash
python scripts/stage1_check.py
```

---

## 📄 Lisans
MIT License
