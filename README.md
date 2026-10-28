# VFS Global Bulgaristan Vize Randevu Botu

Türkiye &rarr; Bulgaristan VFS Global vize başvuru portalı (`https://visa.vfsglobal.com/tur/en/bgr/`) için geliştirilmiş, ban korumalı ve iki katmanlı hibrit randevu tespit ve rezervasyon otomasyon sistemi.

---

## 🚀 Özellikler

### 1. İki Katmanlı Mimari (Plan v2)
* **Katman 0 (Public Sweep — Sıfır Hesap Riski)**:
  - `POST /appointment/centerwithearliestslot` çağrısı ile hesap girişi yapmadan, OTP harcamadan ve ban riski olmadan tüm merkezler (İstanbul, Ankara, Edirne, Bursa, İzmir) ve kategoriler için en erken randevu tarihlerini 5-8 dakika aralıklarla yoklar.
  - Tarih aralığı (`tarih_baslangic`, `tarih_bitis`) ve başvuru merkezi tercihi eşleştirmesi.
  - SHA-1 hash ile mükerrer bildirim engelleme (deduplication).
* **Katman 1 (Hedefli Doğrulama & Otomatik Rezervasyon)**:
  - Yalnızca uygun tarihli bir slot tespit edildiğinde veya kullanıcı talep ettiğinde devreye girer.
  - Oturum koruması: Geçerli oturum varsa tekrar login olmaz (24 saatlik 429202 kilitlenmesini önler).
  - Giriş bütçesi (max 3 deneme) denetimi.
  - Hedefli IMAP e-posta OTP köprüsü ile 6 haneli doğrulama kodunu otomatik alma.
  - Hazır başvuran yükü ile `<500 ms` içinde `POST /appointment/bookappointment` isteği gönderme.

### 2. İnsansı Anti-Detect & Cloudflare Turnstile Çözümü (Aşama 1)
* **Patchright + Resmi Google Chrome**: CDP sızıntılarını ve tarayıcı otomasyon bayraklarını temizler.
* **Kalıcı Profil (Persistent Context)**: Kullanıcı çerezlerini ve oturum geçmişini korur.
* **İnsansı Davranış Modelleri**: Kübik Bézier fare eğrileri, mikrotitremeler (micro-tremor), doğal sayfa kaydırma ve değişken zamanlamalar.

### 3. Modern Web Kontrol Paneli
* **Cam Efektli (Glassmorphism) Arayüz**: Outfit & Inter tipografisi, koyu tema.
* **4 KPI Metrik Kartı**: Aktif Başvuranlar, Tespit Edilen Slotlar, Alınan Randevular, Son Tarama Zamanı.
* **Excel & SQLite İki Yönlü Eşitleme**: 23 sütunlu başvuran listesini yönetme ve canlı durum takibi (`PENDING`, `SLOT_FOUND`, `BOOKED`, `COOLDOWN`).
* **Canlı Konsol & Ekran Görüntüsü**: Bot loglarını ve Cloudflare Turnstile doğrulama kanıtlarını canlı izleme.
* **Entegre Test Araçları**: Telegram bildirim testi ve IMAP e-posta bağlantı testi.

---

## 🛠️ Kurulum

### Gereksinimler
* Python 3.10+
* Google Chrome (resmi sürüm)
* Git

```bash
# Depoyu klonlayın
git clone https://github.com/tracecorp24/deneme-1.git
cd deneme-1

# Gerekli bağımlılıkları yükleyin
pip install -r requirements.txt

# Patchright tarayıcı bileşenlerini kurun
patchright install chromium
```

---

## 🏃‍♂️ Çalıştırma

### Kolay Başlatma (Windows)
Masaüstündeki veya klasördeki `start.bat` dosyasına çift tıklayın. Otomatik olarak sunucuyu başlatıp web kontrol panelini (`http://localhost:5000`) tarayıcınızda açacaktır.

### Manuel Başlatma
```bash
python web_app.py
```
Tarayıcınızdan `http://localhost:5000` adresine gidin.

---

## ⚙️ Yapılandırma (`config.yaml`)

* `portal`: Hedef ülke ve dil ayarları.
* `centres`: Başvuru merkezleri (IST, ANK, EDR, BUR, IZM).
* `polling`: Genel tarama ve gece penceresi bekleme süreleri.
* `session`: Oturum ömrü ve giriş bütçesi.
* `proxy`: Residential / ISP proxy havuzu.
* `telegram`: Bot token ve Chat ID.
* `otp`: IMAP e-posta ve filtre ayarları.

---

## 📄 Lisans
MIT License
