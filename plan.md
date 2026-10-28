# VFS Vize Randevu Botu — Tasarım ve Uygulama Planı

*Tam sohbet dökümü*

| Alan | Değer |
|---|---|
| Oluşturma tarihi | 27.10.2026 |
| Hedef portal | https://visa.vfsglobal.com/tur/en/bgr/ (Türkiye → Bulgaristan) |
| Aylık bütçe | 50 USD |
| Mod | Tam otomatik rezervasyon + Excel tabanlı başvuran yönetimi |
| Durum | Tasarım aşaması (henüz kod yazılmadı) |

## İçindekiler

1. [İlk talep ve genel mimari planı](#bölüm-1--i̇lk-talep-ve-genel-mimari-planı)
2. [Bulgaristan VFS özelinde nihai plan](#bölüm-2--bulgaristan-vfs-özelinde-nihai-plan)
3. [Mimari diyagramlar (mermaid)](#bölüm-3--mimari-diyagramlar-mermaid)
4. [Excel şeması](#bölüm-4--excel-şeması)
5. [OTP köprüsü](#bölüm-5--otp-köprüsü)
6. [Oturum ömrü yönetimi](#bölüm-6--oturum-ömrü-yönetimi)
7. [Anti-ban kuralları](#bölüm-7--vfsе-özel-anti-ban-kuralları)
8. [Maliyet tablosu](#bölüm-8--maliyet-tablosu)
9. [Teknoloji yığını](#bölüm-9--teknoloji-yığını)
10. [Yol haritası](#bölüm-10--yol-haritası)
11. [Riskler](#bölüm-11--riskler)
12. [Açık sorular](#bölüm-12--açık-sorular)
13. [Referanslar](#bölüm-13--referanslar)

---

## Bölüm 1 — İlk talep ve genel mimari planı

### Kullanıcı

> Vfs vize alma botu yapacağız sistme öyle olmalı ki 7/24 ayakta ve randevu aruyacak ban yemiyecek proxy ile desteklenebilir ama toplam bütçe 70 doları geçemez sistem için ama yat performans olmalı. Tasarım planla

### Venice

#### 1. Gerçekçi beklenti ayarı

VFS'in en büyük sorunu "kod yazmak" değil, *slot bulmak*. Üç ayrı problem var ve bunları ayrı çözmeniz gerekir:

| Problem | Çözüm yeri |
|---|---|
| Cloudflare / Akamai bot koruması | HTTP katmanı (fingerprint), proxy |
| IP rate-limit / ban | Proxy rotasyonu + sticky session |
| Slot kapma yarışı (milisaniye) | Otomatik rezervasyon yolu |

Kritik karar: *tarayıcı (headless Chrome) ile sürekli polling yapmayın.* Yavaş, RAM yer, parmak izi yakalanır. Doğru yol: VFS'in arka plandaki JSON/XHR endpoint'lerini bulup *saf HTTP ile* konuşmak. Tarayıcıyı sadece login ve son rezervasyon adımında kullanın.

#### 2. Katmanlar

##### A. Keşif (Recon) — 1-2 gün

1. Hedef ülkenin VFS portalını açın, DevTools > Network > Fetch/XHR filtresi.
2. Randevu sayfasında tarih/merkez seçip "ara" dediğinizde giden isteği kopyalayın. Genelde şuna benzer: POST /{country}/{lang}/appointment/checkIsSlotAvailable veya GET .../slot?centerCode=X&dateFrom=...
3. cURL olarak kopyalayıp Python'a çevirin. Gerekli header'lar: Origin, Referer, Accept-Language, X-Requested-With.
4. Aynı isteği *cookie'siz* atın — 403 geliyorsa ısınma (warm-up) zorunlu demektir.

##### B. HTTP çekirdeği

- curl_cffi kullanın (impersonate="chrome"). Bu, JA3/JA4 TLS parmak izini gerçek Chrome'a benzetir — Cloudflare'i geçmenin en ucuz yolu budur.
- httpx/aiohttp tek başına yetmez, çünkü TLS parmak izi Python'a özgüdür ve kolayca yakalanır.
- asyncio ile paralel görevler: merkez × tarih aralığı kombinasyonlarını eşzamanlı tarayın. 20-50 eşzamanlı istek bu iş için fazlasıyla yeterli.
- Her worker: home page → login/cookie kurulumu → slot API şeklinde *ısınma sırası* izler. Çıplak API çağrısı 403 yer.

##### C. Proxy yönetimi

- *Sticky session şart.* VFS, IP değişince oturumu düşürür. Bir proxy IP'si = bir oturum.
- Havuz yapısı: sağlık skoru tutan bir ProxyManager. 403/429 alan IP karantinaya girer, TTL sonunda geri döner.
- İki tip proxy karışımı en verimlisi:
  - *ISP / static residential* → login + rezervasyon (pahalı ama banlanmaz)
  - *Rotating datacenter* → sadece slot yoklaması (çok ucuz, yoğun trafiği taşır)
- Ban yemenin asıl sebebi IP değil, *davranış*. Aynı saniyede 200 istek atan bot anında yakalanır.

##### D. Zamanlayıcı ve durum

- Slot yoklaması: 30-90 saniye arası, *jitter'lı* (sabit aralık = parmak izi).
- Görülen slotlar SQLite'ta hash'lenir → aynı slot için 40 kez Telegram bildirimi gitmez.
- Yeniden deneme: exponential backoff + jitter, tavan 5 dakika.

##### E. Bildirim

- Telegram bot: inline butonlu mesaj → "Merkez: X / Tarih: Y → Rezerve Et".
- Heartbeat: her 10 dakikada bir "hâlâ ayaktayım" + son 24 saatte kaç istek / kaç 403. Bot sessizce öldüğünde haberiniz olur.
- Healthchecks.io (ücretsiz) ile ölü adam anahtarı: cron ping atmazsa Telegram'a alarm.

##### F. Otomatik rezervasyon

- Playwright ile *bir kez elle login* olun, storage_state (cookie + localStorage) diske kaydedin.
- Slot bulunduğunda bu oturumu yükleyip formu doldurup submit eder.
- Mümkünse son adımı da saf HTTP POST ile yapın — tarayıcı açma süresi (2-4 sn) slot kaybettirir.
- CAPTCHA çıkarsa: Faz 1'de Telegram'dan elle çözdürün (bedava). Faz 2'de 2Captcha/CapSolver entegre edin.
- Cloudflare challenge'a girerse: *FlareSolverr* (ücretsiz, aynı VPS'te Docker ile) → cf_clearance cookie'sini alıp HTTP istemcisine devredin.

##### G. Operasyon

- Docker Compose: her servis ayrı konteyner, restart: unless-stopped.
- systemd + Watchtower ile otomatik güncelleme/yeniden başlatma.
- Loglar dosyaya + Telegram'a hata özeti.

#### 3. Anti-ban kuralları (uyulması zorunlu)

1. TLS parmak izi = Chrome (curl_cffi impersonate).
2. UA, sec-ch-ua, Accept-Language impersonate edilen sürümle *birebir tutarlı* olacak.
3. IP başına eşzamanlılık tavanı: 2-4 istek. Aşmayın.
4. Her istekten önce 0.2-1.5 sn rastgele bekleme.
5. Oturum ısınması atlanmayacak (home → login → API).
6. Tek hesap = tek kimlik. 20 farklı IP'den aynı anda login olup oturumu düşürmeyin.
7. 403/429 → o IP'yi 10-30 dakika dinlendir, hemen tekrar denemeyin.
8. Rezervasyon endpoint'ini sadece slot varken dövün, sürekli değil.
9. Gece saatlerinde (hedef ülke saatiyle 02:00-05:00) yoklama aralığını uzatın — VFS'in gece bakım pencereleri var.

#### 4. Altyapı ve maliyet (70 USD varsayımıyla)

| Kalem | Seçim | Aylık |
|---|---|---|
| VPS | Oracle Cloud Always Free (4 ARM çekirdek / 24 GB RAM) | $0 |
| VPS yedek | Hetzner CX22 | ~$4.5 |
| ISP / static residential proxy | 6-8 IP, 2 farklı sağlayıcı | $15-25 |
| Rotating datacenter proxy | Webshare 100 IP paketi | $3-7 |
| CAPTCHA (opsiyonel) | 2Captcha / CapSolver | $3-5 |
| Bildirim + izleme | Telegram + Healthchecks.io | $0 |
| *Toplam* | | *~$22-42* |

#### 5. Teknoloji yığını

text
Python 3.12
├── curl_cffi        # TLS/JA3 impersonation (çekirdek)
├── asyncio          # eşzamanlı worker'lar
├── selectolax/lxml  # HTML parse (gerektiğinde)
├── Playwright       # sadece login + rezervasyon
├── python-telegram-bot
├── SQLite           # durum, dedupe, proxy skoru
├── Docker Compose   # dağıtım
└── FlareSolverr     # Cloudflare fallback


Redis'e gerek yok — tek VPS'te SQLite + asyncio queue yeterli, daha az parça daha az arıza.

#### 6. Yol haritası

| Faz | İçerik | Süre |
|---|---|---|
| 1 | Recon + tek IP'den çalışan HTTP isteği | 1-2 gün |
| 2 | Çoklu merkez/tarih tarama + Telegram bildirim | 2-3 gün |
| 3 | Proxy havuzu, sticky session, ban/backoff mantığı | 2-3 gün |
| 4 | FlareSolverr + otomatik rezervasyon (Playwright) | 3-5 gün |
| 5 | İzleme, heartbeat, otomatik restart, log | 1-2 gün |

*Toplam: ~10-14 gün.*

#### 7. Riskler

- *VFS arayüz değiştirir* → endpoint'ler kayar. Kodu modüler yazın, URL/selector'ları config'de tutun.
- *Hesap banı* → VFS bazen bot hesabını askıya alır. İkinci bir yedek hesapla login yolunu hazırda tutun.
- *Bölgesel geo-fence* → bazı portallar sadece ülke içi IP kabul eder; proxy havuzunda hedef ülke IP'si bulundurun.
- *Slot yarışı* → siz bulsanız da başkası kapabilir; bildirim gecikmesini (Telegram ~1 sn) minimize edin, kritik slotta direkt rezerve edin.

---

## Bölüm 2 — Bulgaristan VFS özelinde nihai plan

### Kullanıcı

> Bulgaristan vfs portalı olacak. Aylık 50 dolar olsun. Tam ptomatik texervasyn olacak elimizde exvell olacak

### Venice

Arama sonuçları işi netleştirdi. Bulgaristan portalı doğrulandı: https://visa.vfsglobal.com/tur/en/bgr/ (Türkiye'den Bulgaristan başvuruları).

Ayrıca kritik bir detay çıktı: *VFS'te başarısız login denemeleri 24 saatlik hesap kilidine yol açıyor* ve OTP kodu 60-90 saniyede geçersiz oluyor. Bu iki gerçek, mimarinin merkezine oturuyor.

#### 1. Mimarinin üç kritik gerçeği

| Gerçek | Tasarıma etkisi |
|---|---|
| Login = e-posta OTP, 60-90 sn ömür | IMAP köprüsü şart, 2-3 sn aralıkla hedefli arama |
| Yanlış login tekrarı = 24 saat kilit | Oturumu *uzun yaşat*, login'i nadir yap |
| Bulgaristan artık Schengen → talep patlaması | Slot yarışı milisaniye işi, payload önceden hazır |

*Sonuç:* Bu bot "sürekli login olan" bir bot değil. "Bir kez login olup oturumu haftalarca taşıyan" bir bot olmalı. Login = en pahalı ve en riskli işlem.

#### 2. Excel şeması

Excel hem girdi hem çıktı olacak. Girdi sütunlarını siz doldurursunuz, çıktı sütunlarını bot yazar.

*Girdi sütunları:* id, ad, soyad, pasaport_no, dogum_tarihi, uyruk, telefon, vfs_email, vfs_sifre, imap_app_sifre, imap_sunucu, merkez_tercih, kategori, tarih_baslangic, tarih_bitis

*Botun yazdığı sütunlar:* durum (PENDING/BOOKED/FAILED), randevu_tarihi, randevu_saati, merkez, referans_no, deneme_sayisi, son_hata, guncelleme_zamani

*Teknik kural:* Excel'e doğrudan yazmayın. SQLite'ı gerçek durum kaynağı yapın, Excel'e 30 saniyede bir atomik yazın (geçici dosyaya yaz → os.replace). Bot çökerse veri kaybolmaz, Excel bozulmaz.

#### 3. Başvuran başına yaşam döngüsü

text
PENDING
  → hesabı doğrula (profil + pasaport bilgisi hesapta KAYITLI mı?)
  → değilse: login → "başvuran ekle" adımını ŞİMDİ yap
  → login (OTP ile)
  → SESSION_ACTIVE
  → slot API'sini yokla (60-120 sn, jitter)
  → slot bulundu
  → hazır payload'ı POST et (hedef: <500 ms)
  → onay sayfasından referans no çek
  → Excel'e yaz + Telegram
  → onay PDF'ini indir, Excel'in yanına kaydet


*Atlanan ama hayati adım:* VFS'te randevu alabilmek için başvuranın hesaba önceden eklenmiş olması gerekir. Bot bunu *slot bulunmadan önce* yapmalı. Slot anında form dolduruyorsanız, yarışı kaybedersiniz.

#### 4. OTP köprüsü (projenin kalbi)

- IMAP bağlantısı: Gmail uygulama şifresi (2FA açıkken normal şifre çalışmaz).
- Arama filtresi: gönderen vfsglobal + konu OTP/verification + son 3 dakika.
- *IMAP IDLE* kullanın (push). Yoksa 2 saniyede bir hedefli SEARCH. Tüm kutuyu taramayın.
- OTP regex: \b\d{6}\b. Kodu bulur bulmaz POST et.
- Bütçe: OTP → submit arası *<5 saniye* olmalı. 90 saniyelik pencerede rahat kalırsınız.
- Eğer bazı hesaplarda OTP SMS ile geliyorsa: Android telefonda ücretsiz "SMS Forwarder" uygulaması + webhook → aynı kuyruğa yazar. Yedek plan olarak hazır tutun.

#### 5. Oturum ömrü yönetimi (24 saat kilidine karşı)

1. *Login denemesi bütçesi: hesap başına 3.* Başarısız olursa o hesabı 30 dakika dinlendir.
2. 3 denemede de OTP gelmezse → hesabı MANUAL_REVIEW'a al, Telegram'dan haber ver. Sakın döngüde login denemeyin.
3. Oturum çerezlerini diske yazın (session_{id}.json), süreç yeniden başlasa bile yeniden login olmayın.
4. Oturum düştüğünde *oturum yenileme* yolunu deneyin (cookie tazeleme) — tam login'den önce.
5. cf_clearance cookie'sini de aynı dosyada saklayın, her istekte yeniden üretmeyin.

#### 6. VFS'e özel anti-ban

- curl_cffi + impersonate="chrome" — TLS parmak izi zorunlu, Cloudflare burada aktif.
- *Hesap = IP eşlemesi sabit.* Bir hesap hep aynı sticky proxy IP'sinden girer. IP değişirse VFS oturumu şüpheli görür.
- Yoklama aralığı: 60-120 sn + %20 jitter. 10 saniyede bir yoklayan botlar 403 yer.
- Cloudflare challenge → FlareSolverr (ücretsiz, aynı sunucuda Docker). Çözdüğü cookie'yi HTTP istemcisine devredin.
- Login ekranında reCAPTCHA → 2Captcha/CapSolver. Login nadir olduğu için maliyeti ayda 1-2 dolara düşer.
- Aynı IP'den eşzamanlı istek tavanı: 3. Hesap sayısı 3'ü geçiyorsa IP sayısını artırın.
- VFS "waiting room"/kuyruk sayfası gösterirse bunu hata saymayın — kuyruk token'ını alıp bekleyin.

#### 7. Maliyet tablosu (50 USD / ay)

| Kalem | Seçim | Aylık |
|---|---|---|
| VPS | Oracle Cloud Always Free (4 ARM / 24 GB) | $0 |
| VPS yedek | Hetzner CX22 (Oracle kapasite vermezse) | $4.5 |
| ISP / static residential proxy | 6-8 IP, 2 sağlayıcı (IPRoyal, Webshare) | $18-24 |
| Rotating datacenter (sadece yoklama) | Webshare 100 IP | $4-6 |
| CAPTCHA | 2Captcha / CapSolver | $3-5 |
| FlareSolverr, Telegram, IMAP, Healthchecks | self-hosted / ücretsiz | $0 |
| *Toplam* | | *~$26-40* |

*$50'de kalıyorsunuz, ~$10-20 yedek.* Bu yedeği ekstra proxy IP'sine harcayın — bu işte en değerli varlık temiz IP'dir.

*Ölçekleme kuralı:* 5 başvurana kadar 3-4 IP yeterli. 10+ başvuruda IP'yi başvuran sayısına yaklaştırın, yoksa aynı IP'den çok oturum yönetirsiniz ve ban riski artar.

#### 8. Teknoloji yığını

text
Python 3.12
├── curl_cffi           # TLS impersonation (çekirdek)
├── asyncio             # başvuran başına bağımsız görev
├── imaplib + email     # OTP köprüsü (IDLE)
├── openpyxl            # Excel okuma/yazma
├── SQLite              # gerçek durum kaynağı + dedupe
├── Playwright          # sadece teşhis/recon, üretimde minimum
├── python-telegram-bot
├── FlareSolverr        # Cloudflare fallback
└── Docker Compose


Redis'e gerek yok. Tek VPS, SQLite + asyncio yeterli — daha az parça, daha az arıza.

#### 9. Fazlar

| Faz | İçerik | Süre |
|---|---|---|
| 1 | Recon: tur/en/bgr üzerinde login + slot API'sini yakala | 1-2 gün |
| 2 | OTP köprüsü + kalıcı oturum + Excel oku/yaz | 2-3 gün |
| 3 | Slot yoklama + Telegram bildirim (çalışan uyarı botu) | 2 gün |
| 4 | Başvuran ön-kaydı + tam otomatik POST rezervasyon | 3-4 gün |
| 5 | Proxy havuzu, kuyruk/backoff, heartbeat, onay PDF indirme | 2 gün |

*~11-13 gün.* Faz 3 sonunda işleyen bir uyarı botunuz olur; faz 4 asıl istediğiniz kısım.

#### 10. Riskler ve gerçekçi not

- *VFS arayüz değiştirir.* Endpoint ve selector'ları config'de tutun, koda gömmeyin.
- *Bulgaristan Schengen sonrası çok yoğun.* Bot slot bulsa da başkası kapabilir; bu yüzden bildirim değil *rezervasyon* yapmak zorundasınız.
- *OTP gecikmesi* en büyük tek arıza noktası. Gmail IMAP bazen 10-20 sn gecikir; IDLE kullanmak bunu çözer.
- *Hesap banı:* VFS bazen bot hesabı askıya alır. Excel'de her başvuranın yedek bir e-posta adresini tutun.
- Açık kaynak referans olarak github.com/ranjan-mohanty/vfs-appointment-bot var, ama VFS o kadar değişti ki sıfırdan yazmak daha hızlı olur — recon'da bunu doğrularız.

#### 11. Netleştirilmesi gereken 3 nokta

1. *Excel'de kaç başvuran var?* (1-5 ise tek IP yeter, 10+ ise proxy bütçesini yeniden dağıtırım)
2. *OTP e-postaya mı, SMS'e mi geliyor?* (VFS Bulgaristan'da e-posta bekleniyor ama hesabınızdan teyit etmek gerekir)
3. *Kaç VFS hesabı var?* Her başvuranın kendi hesabı mı, yoksa grup randevusu mu alıyoruz? (İkincisi çok daha hızlı ve ucuz — tek login ile 5 kişiye kadar rezervasyon mümkün)

---

## Bölüm 3 — Mimari diyagramlar (mermaid)

Aşağıdaki kodları https://mermaid.live adresine yapıştırıp çalıştırabilirsiniz.

### Diyagram 1 — Genel mimari

mermaid
flowchart TD
    subgraph VPS["VPS / Cloud Instance"]
        Sched["Scheduler / Orchestrator"]
        Q["Queue"]
        DB[("SQLite State Store")]
        Pool["Async Worker Pool"]
        FS["FlareSolverr Headless Browser Fallback"]
        PW["Playwright Booking Worker"]
        TG["Telegram Bot Controller"]
        HM["Health / Uptime Monitor"]
    end

    subgraph Ext["External Services"]
        PM["Proxy Manager (sticky sessions + rotation)"]
        TGCloud["Telegram Cloud"]
        CAPTCHA["CAPTCHA Solving Service (optional)"]
    end

    VFS["VFS Global Endpoints"]

    Sched --> Q
    Q --> Pool
    Q -.-> DB
    Pool -.-> DB

    Pool --> PM
    PM --> VFS

    Pool --> FS
    FS --> VFS

    Pool --> TG
    TG --> TGCloud
    TGCloud --> PW
    PW --> VFS
    PW -.-> DB

    FS -.-> CAPTCHA
    PW -.-> CAPTCHA

    HM -.-> Pool
    HM --> TG


### Diyagram 2 — İstek işleme ve anti-ban mantığı

mermaid
flowchart TD
    A(["Start: get task from queue"]) --> B{"Is sticky session alive?"}

    B -->|"yes"| C["Reuse existing session"]
    B -->|"no"| D["Warm up new session"]

    D --> D1["Fetch home page"]
    D1 --> D2["Set cookies"]
    D2 --> E
    C --> E["Send request with TLS/JA3 impersonation"]

    E --> F{"HTTP response status"}

    F -->|"200 OK"| G["Parse slots"]
    G --> H{"Slot found?"}
    H -->|"yes"| I["Send notification"]
    H -->|"no"| J["Reschedule with jitter"]

    F -->|"403 / 429"| K["Mark proxy IP in cooldown"]
    K --> L["Apply exponential backoff"]
    L --> M["Rotate proxy"]

    F -->|"Cloudflare challenge"| N["Route through FlareSolverr"]
    N --> O["Obtain cf_clearance cookie"]
    O --> P["Retry request"]

    F -->|"5xx server error"| Q["Retry with backoff"]

    I --> R(["Loop back to queue"])
    J --> R
    M --> R
    P --> R
    Q --> R
    R --> A


### Diyagram 3 — Başvuran yaşam döngüsü

mermaid
stateDiagram-v2
    [*] --> PENDING

    PENDING --> LOGGING_IN
    LOGGING_IN --> AWAITING_OTP
    AWAITING_OTP --> SESSION_ACTIVE : OTP success
    AWAITING_OTP --> RETRY_BACKOFF : OTP timeout
    SESSION_ACTIVE --> POLLING_SLOTS
    POLLING_SLOTS --> SLOT_FOUND : slot detected
    SLOT_FOUND --> BOOKING
    BOOKING --> BOOKED : confirmation
    BOOKING --> RETRY_BACKOFF : booking failure
    RETRY_BACKOFF --> LOGGING_IN

    LOGGING_IN --> PROXY_COOLDOWN : 403 or 429
    AWAITING_OTP --> PROXY_COOLDOWN : 403 or 429
    SESSION_ACTIVE --> PROXY_COOLDOWN : 403 or 429
    POLLING_SLOTS --> PROXY_COOLDOWN : 403 or 429
    SLOT_FOUND --> PROXY_COOLDOWN : 403 or 429
    BOOKING --> PROXY_COOLDOWN : 403 or 429
    PROXY_COOLDOWN --> RETRY_BACKOFF

    LOGGING_IN --> MANUAL_REVIEW : 5 consecutive captcha failures
    MANUAL_REVIEW --> RETRY_BACKOFF : manual resolution

    PENDING --> FAILED
    MANUAL_REVIEW --> FAILED
    RETRY_BACKOFF --> FAILED : max retries exhausted

    BOOKED --> [*]
    FAILED --> [*]


### Diyagram 4 — Tam otomatik rezervasyon akışı

mermaid
sequenceDiagram
    participant BO as "Bot Orchestrator"
    participant SP as "Sticky Proxy"
    participant VFS as "VFS Portal"
    participant AEI as "Applicant Email Inbox"
    participant EF as "Excel File"
    participant TG as "Telegram"

    BO->>EF: "Read applicant row (credentials, centers, date range)"
    EF-->>BO: "Row data"

    BO->>SP: "Login request with stored credentials"
    SP->>VFS: "Forward login request"
    VFS->>AEI: "Send 6-digit OTP to applicant email"

    BO->>AEI: "Poll inbox via IMAP and extract OTP"
    AEI-->>BO: "OTP code"

    BO->>VFS: "Submit OTP"
    VFS-->>BO: "Session cookies"

    loop "Poll slots with exponential backoff"
        BO->>VFS: "Poll slot availability endpoint"
        alt "No slot available"
            VFS-->>BO: "No slots"
            Note over BO: "Wait with exponential backoff, then retry"
        else "403 Forbidden"
            VFS-->>BO: "403 Forbidden"
            Note over BO,SP: "Rotate sticky proxy session and retry"
        end
    end

    VFS-->>BO: "Slot available"
    BO->>VFS: "Post pre-built booking payload with applicant details"
    VFS-->>BO: "Booking confirmation with reference number"

    BO->>EF: "Write BOOKED status and reference number"
    BO->>TG: "Send booking notification"


---

## Bölüm 4 — Excel şeması

Kopyala-yapıştır başlık satırı (sekme ile ayırın):

text
id	ad	soyad	pasaport_no	dogum_tarihi	uyruk	telefon	vfs_email	vfs_sifre	imap_app_sifre	imap_sunucu	merkez_tercih	kategori	tarih_baslangic	tarih_bitis	durum	randevu_tarihi	randevu_saati	merkez	referans_no	deneme_sayisi	son_hata	guncelleme_zamani


| Sütun | Örnek | Not |
|---|---|---|
| id | 1 | Birincil anahtar |
| ad, soyad | — | VFS'teki yazımla birebir |
| pasaport_no | — | |
| dogum_tarihi | 1990-05-12 | ISO format |
| uyruk | TR | |
| telefon | +90... | |
| vfs_email | a@gmail.com | VFS hesabının e-postası |
| vfs_sifre | — | |
| imap_app_sifre | — | Gmail uygulama şifresi (OTP okuma) |
| imap_sunucu | imap.gmail.com | |
| merkez_tercih | IST, BUR, ANK | Virgülle, öncelik sırasıyla |
| kategori | turistik / is / transit | |
| tarih_baslangic, tarih_bitis | 2026-11-01 / 2026-12-31 | |

Botun yazdığı sütunlar: durum, randevu_tarihi, randevu_saati, merkez, referans_no, deneme_sayisi, son_hata, guncelleme_zamani.

---

## Bölüm 5 — OTP köprüsü

- Gmail'de 2 adımlı doğrulamayı açın, ardından "Uygulama şifresi" üretin. Normal Gmail şifresi IMAP'te çalışmaz.
- *IMAP IDLE* ile push alın; yoksa 2 saniyede bir hedefli SEARCH.
- Filtre: FROM vfsglobal + SUBJECT (OTP veya verification) + bugün.
- Regex: \b\d{6}\b
- OTP → form submit arası hedef: *<5 saniye*.
- SMS OTP durumu için yedek: Android + "SMS Forwarder" uygulaması + HTTP webhook → aynı kuyruğa yazar.
- OTP penceresi 60-90 saniye. 90 saniye geçerse OTP'yi yeniden isteyin, ama login denemesi sayacını artırmayın.

---

## Bölüm 6 — Oturum ömrü yönetimi

1. Hesap başına login denemesi: *max 3*, sonra 30 dk dinlenme.
2. 3 denemede OTP gelmezse MANUAL_REVIEW + Telegram uyarısı.
3. Çerezler diske: session_{id}.json (cookie + localStorage + cf_clearance).
4. Süreç yeniden başlarsa önce çerezden devam et, login denemeyin.
5. Tam login'den önce "cookie tazeleme" yolunu dene.
6. cf_clearance cookie'sini tekrar üretme, sakla ve kullan.

---

## Bölüm 7 — VFS'e özel anti-ban kuralları

1. curl_cffi + impersonate="chrome" — TLS/JA3 parmak izi zorunlu.
2. UA, sec-ch-ua, Accept-Language impersonate edilen sürümle birebir uyumlu.
3. Hesap = sabit sticky proxy IP. Bir hesap hep aynı IP'den girer.
4. IP başına eşzamanlı istek tavanı: 3.
5. Yoklama aralığı: 60-120 sn + %20 jitter.
6. Oturum ısınma sırası: home → login → slot API. Atlanmayacak.
7. 403/429 → IP'yi 10-30 dk karantinaya al.
8. Rezervasyon endpoint'i sadece slot varken çağrılır.
9. Gece 02:00-05:00 arası yoklamayı seyrelt.
10. Cloudflare challenge → FlareSolverr.
11. reCAPTCHA → 2Captcha/CapSolver (yalnızca login anında).
12. "Waiting room" / kuyruk sayfasını hata sayma, token'ı al ve bekle.

---

## Bölüm 8 — Maliyet tablosu

| Kalem | Seçim | Aylık |
|---|---|---|
| VPS | Oracle Cloud Always Free | $0 |
| VPS yedek | Hetzner CX22 | $4.5 |
| ISP / static residential proxy | 6-8 IP, 2 sağlayıcı | $18-24 |
| Rotating datacenter (yoklama) | Webshare 100 IP | $4-6 |
| CAPTCHA | 2Captcha / CapSolver | $3-5 |
| Diğer (Telegram, IMAP, Healthchecks, FlareSolverr) | ücretsiz | $0 |
| *Toplam* | | *~$26-40* |

Kalan bütçe (~$10-20) yedek proxy IP'sine ayrılmalı. Bu işte en değerli varlık temiz IP'dir.

*Ölçekleme:* 5 başvurana kadar 3-4 IP. 10+ başvuruda IP sayısını başvuran sayısına yaklaştır.

---

## Bölüm 9 — Teknoloji yığını

text
Python 3.12
├── curl_cffi            # TLS impersonation (çekirdek)
├── asyncio              # başvuran başına bağımsız görev
├── imaplib + email      # OTP köprüsü (IDLE)
├── openpyxl             # Excel okuma/yazma
├── SQLite               # gerçek durum kaynağı + dedupe
├── Playwright           # teşhis/recon
├── python-telegram-bot  # bildirim
├── FlareSolverr         # Cloudflare fallback
└── Docker Compose       # dağıtım


Redis gerekmez. Tek VPS, SQLite + asyncio yeterli.

---

## Bölüm 10 — Yol haritası

| Faz | İçerik | Süre |
|---|---|---|
| 1 | Recon: tur/en/bgr üzerinde login + slot API'si | 1-2 gün |
| 2 | OTP köprüsü + kalıcı oturum + Excel oku/yaz | 2-3 gün |
| 3 | Slot yoklama + Telegram bildirim | 2 gün |
| 4 | Başvuran ön-kaydı + tam otomatik POST rezervasyon | 3-4 gün |
| 5 | Proxy havuzu, kuyruk/backoff, heartbeat, PDF | 2 gün |

Toplam: *~11-13 gün*

- Faz 3 sonunda: çalışan uyarı botu
- Faz 4 sonunda: tam otomatik rezervasyon botu (asıl hedef)

---

## Bölüm 11 — Riskler

1. *VFS arayüz değişikliği* → endpoint ve selector'lar config'de tutulmalı.
2. *Bulgaristan Schengen sonrası yoğunluk* → rezervasyon şart, bildirim yetmez.
3. *OTP gecikmesi* → en büyük tek arıza noktası. IMAP IDLE ile çözülür.
4. *Hesap banı* → her başvuran için yedek e-posta tutulmalı.
5. *Login kilidi (24 saat)* → login denemesi bütçesi zorunlu.
6. *Geo-fence* → proxy havuzunda hedef ülke IP'si bulundurulmalı.
7. *Slot yarışı* → payload önceden hazırlanmalı, POST <500 ms hedefi.

---

## Bölüm 12 — Açık sorular

1. Excel'de kaç başvuran var? (1-5 ise tek IP yeter, 10+ ise proxy bütçesi yeniden dağıtılır)
2. OTP e-postaya mı, SMS'e mi geliyor? (VFS Bulgaristan'da e-posta bekleniyor, hesaptan teyit gerekli)
3. Kaç VFS hesabı var? Her başvuranın kendi hesabı mı, grup randevusu mu? (Grup randevusu çok daha hızlı ve ucuz — tek login ile 5 kişiye kadar rezervasyon mümkün)

Bu üçüne cevap verilince: recon hedef endpoint listesi + Excel şablonu doğrudan üretilebilir.

---

## Bölüm 13 — Referanslar

*Doğrulanan portal*

- https://visa.vfsglobal.com/tur/en/bgr/
- https://visa.vfsglobal.com/tur/en/bgr/apply-visa

*Bulgaristan VFS ile ilgili diğer ülke portalları (yapı referansı)*

- https://visa.vfsglobal.com/usa/en/bgr/
- https://visa.vfsglobal.com/gbr/en/bgr
- https://visa.vfsglobal.com/ind/en/bgr

*OTP / login kilidi kaynakları*

- https://www.justanswer.com/software/rtcr2-struggling-book-appointment-online-system.html
  - Başarısız login tekrarı 24 saatlik blok yaratıyor.
  - OTP kodları 60-90 saniye geçerli.

*Açık kaynak referans projeler*

- https://github.com/ranjan-mohanty/vfs-appointment-bot
- https://pypi.org/project/vfs-appointment-bot/
- https://github.com/topics/vfs-appointment
- https://github.com/topics/vfs-global

*Chrome eklentisi (rakip bot yaklaşımı)*

- https://chromewebstore.google.com/detail/iffgkfeecbmnodhpnpjbgoillaflhflm

*Topluluk tartışması (anti-bot deneyimleri)*

- https://www.reddit.com/r/n8n/comments/1nj590a/

*Hazır bot servisleri (fiyat kıyaslaması)*

- https://visaslot365.com/customer/intr/vfs.html
- https://www.upwork.com/services/product/development-it-vfs-global-booking-automation-bot-1770846114297978880
