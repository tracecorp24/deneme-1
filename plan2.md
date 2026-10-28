Bulgu	Kanıt	Plana etkisi
API hostu lift-api.vfsglobal.com, Cloudflare arkasında	Reddit + repo ölçümleri	Doğrulandı
Datacenter IP'ler komple reddediliyor (403201, ASN hosting:true)	DigitalOcean Bangalore ölçümü	Webshare datacenter proxy işe yaramaz. Hepsi residential/ISP olmalı
Login'siz public endpoint var: POST /appointment/centerwithearliestslot — tek çağrıda tüm merkezler × tüm kategoriler	Çalışan kod + örnek response	Slot tespiti için login/OTP riskine hiç girmeye gerek yok
cf_clearance cookie'si IP + User-Agent'a bağlı, ömrü 15-30 dk	Ölçüm tablosu	Cookie + UA + IP üçlüsü sabit tutulmalı
Playwright'ın kendi Chromium'u Cloudflare'de bloke; gerçek Chrome/Brave geçiyor	Ölçüm	VPS'e gerçek Chrome kurulacak
409 {"code":N,"description":"Repeated Delay"} → N = kaç saniye bekleyeceğin	Test sonucu	Poll aralığını sunucu söylüyor, tahmin etmiyoruz
200 içinde error.code 1035 = "slot yok" (hata değil)	Test sonucu	Parse mantığı buna göre
OTP her login'de gerekiyor; ~15 login/90dk sonra ~2 saatlik Cloudflare cool-off	Ölçüm	"Az login, uzun oturum" stratejisi doğru
Public veri zaten 15-60 dk gecikmeli geliyor	lastUpdatedOn ölçümü	30 saniyede bir yoklamanın anlamı yok, 5-8 dk yeter
Plan v2 — iki katmanlı mimari
Orijinal plan "sürekli login olan bot" varsayıyordu. Recon gösterdi ki doğru tasarım şu:

KATMAN 0 — Public Sweep (login YOK, sıfır hesap riski)
  POST /appointment/centerwithearliestslot  →  tüm merkez × kategori, tek çağrı
  Sadece 1 geçerli cf_clearance gerekir. Hesap kilidi imkânsız. OTP yok.
  5-8 dk aralık yeter. Bütçenin %80'i burada çözülür.

KATMAN 1 — Hedefli Doğrulama + Rezervasyon (login VAR)
  Public sweep tarih gördüğünde VEYA 20-25 dk'da bir: login → CheckIsSlotAvailable
  authorize JWT ile hızlı yol (~0.4 sn), 409 delay'e harfiyen uyulur.
  Oturum ng2-idle (~20 dk) keep-alive ile canlı tutulur.
Bu, aylık login sayısını ~50'den ~15'e indirir ve 24 saatlik kilit riskini büyük ölçüde ortadan kaldırır.

mermaid
flowchart TD
    A["Public Sweep<br/>(login yok, 5-8 dk)"] --> B{"Tarih pencerede mi?"}
    B -->|hayır| A
    B -->|evet| C["Telegram alarm + Kuyruğa at"]
    C --> D["Login Worker<br/>(sticky proxy + gerçek Chrome)"]
    D --> E["OTP köprüsü (IMAP)"]
    E --> F["authorize JWT al"]
    F --> G["CheckIsSlotAvailable<br/>409 ise N sn bekle"]
    G --> H["Payload POST — hedef &lt;500 ms"]
    H --> I["Referans no → SQLite → Excel → Telegram"]
Kod — Faz 1 + Faz 2 iskeleti
requirements.txt
txt
curl_cffi>=0.7.3
playwright>=1.45
openpyxl>=3.1
PyYAML>=6.0
Telegram için ağır framework yok — Bot API'yi doğrudan çağırıyorum, bir bağımlılık eksiliyor.

config.yaml
yaml
portal:
  base: "https://visa.vfsglobal.com/tur/en/bgr"
  country_code: "tur"
  mission_code: "bgr"
  culture_code: "en-US"
  login_path: "/login"
  x_auth_token: "RECON_ILE_DOLDUR"   # SPA'nın gönderdiği statik token

api:
  base: "https://lift-api.vfsglobal.com"
  public_earliest: "/appointment/centerwithearliestslot"
  check_slot: "/appointment/CheckIsSlotAvailable"
  login: "/user/login"               # recon ile teyit
  validate_otp: "/user/validateotp"  # recon ile teyit
  book: "/appointment/bookappointment"  # recon ile teyit

centres:                             # öncelik sırası
  - { code: "IST", name: "Istanbul" }
  - { code: "ANK", name: "Ankara" }
  - { code: "EDR", name: "Edirne" }

categories:
  - { code: "SCHENGEN", match: "Schengen" }
  - { code: "LONGSTAY", match: "Long Stay" }

polling:
  public_interval_s: [300, 480]
  login_verify_interval_s: [1200, 1800]
  api_pause_s: [10, 20]
  night_window: ["02:00", "05:00"]
  night_multiplier: 2.0
  delay_honor_margin_s: 3

session:
  idle_logout_s: 1200
  keepalive_interval_s: 600
  cf_clearance_ttl_s: 1500
  login_budget: 3
  login_cooldown_s: 1800

http:
  impersonate: "chrome"
  timeout_s: 25
  per_ip_concurrency: 3

proxy:
  isp_pool: []                       # ZORUNLU: residential/ISP. datacenter lift-api'de 403 yer.
  health_cooldown_s: 900

otp:
  imap_port: 993
  sender_filter: "vfsglobal"
  subject_filter: ["OTP", "verification", "code"]
  search_window_s: 180
  poll_interval_s: 2
  otp_timeout_s: 85
  regex: "\\b(\\d{6})\\b"

excel:
  path: "data/basvuranlar.xlsx"
  sheet: "Applicants"
  sync_interval_s: 30

telegram:
  heartbeat_s: 600

paths:
  data_dir: "data"
  session_dir: "data/sessions"
  log_dir: "logs"
bot/config.py
python
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("VFSBOT_CONFIG", ROOT / "config.yaml"))


class Cfg(dict):
    def path(self, dotted: str, default: Any = None) -> Any:
        node: Any = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load_config() -> Cfg:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    raw.setdefault("telegram", {})
    raw["telegram"]["token"] = os.getenv("TELEGRAM_TOKEN", raw["telegram"].get("token", ""))
    raw["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", raw["telegram"].get("chat_id", ""))

    raw.setdefault("paths", {})
    for key, default in (("data_dir", "data"), ("session_dir", "data/sessions"), ("log_dir", "logs")):
        raw["paths"][key] = str(ROOT / raw["paths"].get(key, default))
        Path(raw["paths"][key]).mkdir(parents=True, exist_ok=True)

    return Cfg(raw)


CFG = load_config()
bot/db.py
python
"""SQLite = tek doğruluk kaynağı. Excel sadece onun görünümü."""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from typing import Any, Iterable

from .config import CFG

SCHEMA = """
CREATE TABLE IF NOT EXISTS applicants (
    id INTEGER PRIMARY KEY,
    ad TEXT, soyad TEXT, pasaport_no TEXT, dogum_tarihi TEXT,
    uyruk TEXT, telefon TEXT,
    vfs_email TEXT UNIQUE, vfs_sifre TEXT,
    imap_app_sifre TEXT, imap_sunucu TEXT,
    merkez_tercih TEXT, kategori TEXT,
    tarih_baslangic TEXT, tarih_bitis TEXT,
    durum TEXT DEFAULT 'PENDING',
    randevu_tarihi TEXT, randevu_saati TEXT, merkez TEXT, referans_no TEXT,
    deneme_sayisi INTEGER DEFAULT 0,
    son_hata TEXT, guncelleme_zamani TEXT,
    proxy_id INTEGER, yedek_email TEXT
);
CREATE TABLE IF NOT EXISTS slots_seen (
    hash TEXT PRIMARY KEY, merkez TEXT, kategori TEXT, tarih TEXT, ilk_gorulme TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    account_id TEXT PRIMARY KEY, proxy_id INTEGER, user_agent TEXT,
    cf_clearance TEXT, cookies TEXT, authorize TEXT, x_auth_token TEXT,
    updated_at REAL, cf_expires_at REAL
);
CREATE TABLE IF NOT EXISTS proxy_health (
    proxy TEXT PRIMARY KEY, fail_count INTEGER DEFAULT 0,
    cooldown_until REAL DEFAULT 0, last_ok REAL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, level TEXT,
    applicant_id INTEGER, mesaj TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

INPUT_COLS = [
    "id", "ad", "soyad", "pasaport_no", "dogum_tarihi", "uyruk", "telefon",
    "vfs_email", "vfs_sifre", "imap_app_sifre", "imap_sunucu",
    "merkez_tercih", "kategori", "tarih_baslangic", "tarih_bitis", "yedek_email",
]
OUTPUT_COLS = [
    "durum", "randevu_tarihi", "randevu_saati", "merkez", "referans_no",
    "deneme_sayisi", "son_hata", "guncelleme_zamani",
]


class DB:
    def __init__(self, path: str | None = None):
        self.path = path or f"{CFG['paths']['data_dir']}/state.db"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- düşük seviye ----
    def q(self, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)))

    def x(self, sql: str, params: Iterable = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def now(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    # ---- başvuran ----
    def upsert_applicant(self, row: dict[str, Any]) -> None:
        cols = [c for c in INPUT_COLS if c in row and row[c] not in (None, "")]
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        self.x(
            f"INSERT INTO applicants ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [row[c] for c in cols],
        )

    def applicants(self, durum: Iterable[str] | None = None) -> list[sqlite3.Row]:
        if durum:
            marks = ", ".join("?" for _ in durum)
            return self.q(f"SELECT * FROM applicants WHERE durum IN ({marks})", list(durum))
        return self.q("SELECT * FROM applicants ORDER BY id")

    def set_status(self, applicant_id: int, durum: str | None = None, **fields: Any) -> None:
        sets, params = [], []
        if durum:
            sets.append("durum=?")
            params.append(durum)
        for k, v in fields.items():
            if k in OUTPUT_COLS:
                sets.append(f"{k}=?")
                params.append(v)
        sets.append("guncelleme_zamani=?")
        params.append(self.now())
        params.append(applicant_id)
        self.x(f"UPDATE applicants SET {', '.join(sets)} WHERE id=?", params)

    def bump_attempt(self, applicant_id: int, hata: str = "") -> None:
        self.x(
            "UPDATE applicants SET deneme_sayisi=deneme_sayisi+1, son_hata=?, guncelleme_zamani=? WHERE id=?",
            (hata[:500], self.now(), applicant_id),
        )

    # ---- slot dedupe ----
    def slot_is_new(self, slot_hash: str, merkez: str, kategori: str, tarih: str) -> bool:
        rows = self.q("SELECT 1 FROM slots_seen WHERE hash=?", (slot_hash,))
        if rows:
            return False
        self.x(
            "INSERT OR IGNORE INTO slots_seen (hash, merkez, kategori, tarih, ilk_gorulme) VALUES (?,?,?,?,?)",
            (slot_hash, merkez, kategori, tarih, self.now()),
        )
        return True

    # ---- oturum ----
    def session_load(self, account_id: str) -> dict[str, Any] | None:
        rows = self.q("SELECT * FROM sessions WHERE account_id=?", (account_id,))
        if not rows:
            return None
        s = dict(rows[0])
        s["cookies"] = json.loads(s["cookies"] or "[]")
        return s

    def session_save(self, account_id: str, **fields: Any) -> None:
        fields["account_id"] = account_id
        fields["updated_at"] = time.time()
        if "cookies" in fields and not isinstance(fields["cookies"], str):
            fields["cookies"] = json.dumps(fields["cookies"])
        cols = list(fields)
        self.x(
            f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(account_id) DO UPDATE SET "
            f"{', '.join(f'{c}=excluded.{c}' for c in cols if c != 'account_id')}",
            [fields[c] for c in cols],
        )

    def session_clear(self, account_id: str) -> None:
        self.x("DELETE FROM sessions WHERE account_id=?", (account_id,))

    # ---- proxy sağlığı ----
    def proxy_penalize(self, proxy: str, seconds: float) -> None:
        self.x(
            "INSERT INTO proxy_health (proxy, fail_count, cooldown_until) VALUES (?,1,?) "
            "ON CONFLICT(proxy) DO UPDATE SET fail_count=fail_count+1, cooldown_until=?",
            (proxy, time.time() + seconds, time.time() + seconds),
        )

    def proxy_ok(self, proxy: str) -> None:
        self.x(
            "INSERT INTO proxy_health (proxy, fail_count, cooldown_until, last_ok) VALUES (?,0,0,?) "
            "ON CONFLICT(proxy) DO UPDATE SET fail_count=0, cooldown_until=0, last_ok=?",
            (proxy, time.time(), time.time()),
        )

    def proxy_cooling(self, proxy: str) -> bool:
        rows = self.q("SELECT cooldown_until FROM proxy_health WHERE proxy=?", (proxy,))
        return bool(rows and rows[0]["cooldown_until"] > time.time())

    # ---- log / meta ----
    def log(self, level: str, mesaj: str, applicant_id: int | None = None) -> None:
        self.x(
            "INSERT INTO events (ts, level, applicant_id, mesaj) VALUES (?,?,?,?)",
            (self.now(), level, applicant_id, mesaj[:2000]),
        )

    def meta_set(self, k: str, v: str) -> None:
        self.x("INSERT INTO meta (k,v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def meta_get(self, k: str, default: str | None = None) -> str | None:
        rows = self.q("SELECT v FROM meta WHERE k=?", (k,))
        return rows[0]["v"] if rows else default


DB = DB()
bot/proxy.py
python
"""Sticky eşleme: hesap → proxy. cf_clearance IP'ye bağlı olduğu için asla değişmez."""
from __future__ import annotations
import asyncio
import hashlib
from contextlib import asynccontextmanager

from .config import CFG
from .db import DB


class ProxyManager:
    def __init__(self, pool: list[str] | None = None):
        self.pool = [p for p in (pool or CFG["proxy"]["isp_pool"]) if p]
        self._sems = {p: asyncio.Semaphore(int(CFG["http"]["per_ip_concurrency"])) for p in self.pool}
        self._fallback = asyncio.Semaphore(1)

    def assign(self, account_id: str) -> str:
        """Deterministik + kalıcı eşleme. Aynı hesap her zaman aynı IP."""
        if not self.pool:
            return ""
        saved = DB.meta_get(f"proxy:{account_id}")
        if saved and saved in self.pool:
            return saved
        idx = int(hashlib.sha1(account_id.encode()).hexdigest(), 16) % len(self.pool)
        proxy = self.pool[idx]
        DB.meta_set(f"proxy:{account_id}", proxy)
        return proxy

    def healthy(self, account_id: str) -> str:
        """Karantinadaysa sıradaki sağlıklı IP'ye geç (geçici, eşleme korunur)."""
        primary = self.assign(account_id)
        if primary and not DB.proxy_cooling(primary):
            return primary
        for p in self.pool:
            if not DB.proxy_cooling(p):
                return p
        return primary

    @asynccontextmanager
    async def slot(self, proxy: str):
        sem = self._sems.get(proxy) or self._fallback
        async with sem:
            yield

    def penalize(self, proxy: str, seconds: float | None = None) -> None:
        if proxy:
            DB.proxy_penalize(proxy, seconds or float(CFG["proxy"]["health_cooldown_s"]))

    def mark_ok(self, proxy: str) -> None:
        if proxy:
            DB.proxy_ok(proxy)
bot/http.py — curl_cffi + cf_clearance yönetimi
python
"""TLS parmak izi + Cloudflare kapısı. 403 burada yakalanır, çağırana sızmaz."""
from __future__ import annotations
import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

from curl_cffi.requests import AsyncSession

from .config import CFG
from .db import DB
from .proxy import ProxyManager

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class VfsHttp:
    """cf_clearance IP+UA'ya bağlı olduğu için: bir identity = bir (proxy, UA, cookie) üçlüsü."""

    def __init__(self, proxy_mgr: ProxyManager):
        self.proxy_mgr = proxy_mgr
        self._sessions: dict[str, AsyncSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, identity: str) -> asyncio.Lock:
        return self._locks.setdefault(identity, asyncio.Lock())

    async def _session(self, identity: str, proxy: str) -> AsyncSession:
        if identity in self._sessions:
            return self._sessions[identity]
        sess = AsyncSession(
            impersonate=CFG["http"]["impersonate"],
            timeout=float(CFG["http"]["timeout_s"]),
            proxies={"http": proxy, "https": proxy} if proxy else None,
        )
        self._sessions[identity] = sess
        return sess

    # ---------- Cloudflare ----------
    async def ensure_cf_clearance(self, identity: str, proxy: str) -> bool:
        """Geçerli cf_clearance yoksa gerçek Chrome ile üret. Datacenter IP'de işe yaramaz."""
        async with self._lock(identity):
            s = DB.session_load(identity)
            if s and s.get("cf_clearance") and (s.get("cf_expires_at") or 0) > time.time():
                return True
            cookie, ua = await self._mint_cf_clearance(proxy)
            if not cookie:
                DB.log("WARN", f"cf_clearance üretilemedi: {identity}")
                return False
            DB.session_save(
                identity,
                proxy_id=None,
                user_agent=ua,
                cf_clearance=cookie,
                cf_expires_at=time.time() + float(CFG["session"]["cf_clearance_ttl_s"]),
            )
            DB.log("INFO", f"cf_clearance tazelendi: {identity}")
            return True

    async def _mint_cf_clearance(self, proxy: str) -> tuple[str | None, str]:
        """Playwright'ın Chromium'u Cloudflare'de bloke → channel='chrome' şart."""
        from playwright.async_api import async_playwright

        launch_kwargs: dict[str, Any] = {"channel": "chrome", "headless": True}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            # DİKKAT: locale/timezone/viewport emülasyonu Turnstile'ı bozuyor → boş context
            ctx = await browser.new_context()
            page = await ctx.new_page()
            try:
                await page.goto(CFG["portal"]["base"], wait_until="domcontentloaded", timeout=45000)
                for _ in range(40):
                    cookies = await ctx.cookies("https://lift-api.vfsglobal.com")
                    hit = next((c for c in cookies if c["name"] == "cf_clearance"), None)
                    if hit:
                        ua = await page.evaluate("navigator.userAgent")
                        return hit["value"], ua
                    await asyncio.sleep(1)
                return None, CHROME_UA
            finally:
                await ctx.close()
                await browser.close()

    # ---------- istek ----------
    async def request(
        self,
        method: str,
        url: str,
        *,
        identity: str = "public",
        json_body: dict | None = None,
        headers: dict | None = None,
        retries: int | None = None,
    ):
        proxy = self.proxy_mgr.healthy(identity)
        retries = retries if retries is not None else int(CFG["http"]["max_retries"])

        for attempt in range(retries):
            await self.ensure_cf_clearance(identity, proxy)
            s = await self._session(identity, proxy)
            sess = DB.session_load(identity) or {}

            h = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "tr-TR,tr;q=0.9,en;q=0.8",
                "content-type": "application/json",
                "origin": CFG["portal"]["base"].rstrip("/"),
                "referer": CFG["portal"]["base"].rstrip("/") + "/",
                "user-agent": sess.get("user_agent") or CHROME_UA,  # cf cookie'siyle birebir aynı olmalı
            }
            if sess.get("authorize"):
                h["authorize"] = sess["authorize"]
            h.update(headers or {})

            async with self.proxy_mgr.slot(proxy):
                await asyncio.sleep(random.uniform(0.2, 1.5))
                try:
                    resp = await s.request(method, url, json=json_body, headers=h)
                except Exception as exc:  # ağ hatası
                    DB.log("WARN", f"{method} {url} ağ hatası: {exc}")
                    await asyncio.sleep(min(2 ** attempt + random.random(), 300))
                    continue

            code = resp.status_code

            if code == 200:
                self.proxy_mgr.mark_ok(proxy)
                self._persist_cookies(identity, s)
                return resp

            if code == 409:
                # Sunucu "şu kadar saniye bekle" diyor — harfiyen uy.
                try:
                    wait = int(resp.json().get("code", 30))
                except Exception:
                    wait = 30
                wait += int(CFG["polling"]["delay_honor_margin_s"])
                DB.log("INFO", f"409 Repeated Delay → {wait}s bekleniyor")
                await asyncio.sleep(wait)
                continue

            if code in (403, 429):
                # cf_clearance bayatlamış olabilir → cookie'yi yak, IP'yi dinlendir.
                DB.session_save(identity, cf_clearance=None, cf_expires_at=0)
                self.proxy_mgr.penalize(proxy)
                await asyncio.sleep(min(2 ** attempt * 5 + random.random() * 5, 300))
                proxy = self.proxy_mgr.healthy(identity)
                continue

            if code == 401 and sess.get("authorize"):
                DB.session_save(identity, authorize=None)  # JWT bayat → yeniden login
                return resp

            if 500 <= code < 600:
                await asyncio.sleep(min(2 ** attempt + random.random(), 300))
                continue

            return resp

        DB.log("ERROR", f"{method} {url} {retries} denemede başarısız")
        return None

    def _persist_cookies(self, identity: str, sess: AsyncSession) -> None:
        try:
            jar = [
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in sess.cookies.jar
            ]
            DB.session_save(identity, cookies=jar)
        except Exception:
            pass

    async def close(self) -> None:
        for s in self._sessions.values():
            try:
                await s.close()
            except Exception:
                pass
        self._sessions.clear()
bot/vfs.py — endpoint katmanı
python
"""VFS'e özel iş mantığı. URL'ler config'de; recon sonrası kod değişmeden güncellenir."""
from __future__ import annotations
import hashlib
import re
from typing import Any

from .config import CFG
from .db import DB
from .http import VfsHttp

API = CFG["api"]["base"].rstrip("/")


class VfsClient:
    def __init__(self, http: VfsHttp):
        self.http = http

    # ---------- KATMAN 0: login gerektirmez ----------
    async def public_earliest(self) -> dict | None:
        url = API + CFG["api"]["public_earliest"]
        body = {
            "missionCode": CFG["portal"]["mission_code"],
            "countryCode": CFG["portal"]["country_code"],
            "cultureCode": CFG["portal"]["culture_code"],
        }
        r = await self.http.request(
            "POST", url, identity="public", json_body=body,
            headers={"x-auth-token": CFG["portal"]["x_auth_token"]},
        )
        if not r:
            return None
        try:
            return r.json()
        except Exception:
            DB.log("WARN", f"public_earliest JSON parse hatası: {r.text[:200]}")
            return None

    def parse_public(self, data: dict | None) -> list[dict[str, Any]]:
        """vacList → (merkez, kategori, tarih) satırları. earliestAvailableDate '' ise slot yok."""
        out: list[dict[str, Any]] = []
        for vac in (data or {}).get("vacList", []):
            merkez = vac.get("vacName", "")
            for group in vac.get("visaGroupList", []):
                tarih = (group.get("earliestAvailableDate") or "").strip()
                if not tarih:
                    continue
                out.append({
                    "merkez": merkez,
                    "kategori": group.get("displayName", ""),
                    "tarih": tarih,
                })
        return out

    @staticmethod
    def slot_hash(merkez: str, kategori: str, tarih: str) -> str:
        return hashlib.sha1(f"{merkez}|{kategori}|{tarih}".encode()).hexdigest()

    # ---------- KATMAN 1: login gerekir ----------
    async def check_slot(self, account_id: str, vac_code: str, visa_category_code: str) -> dict | None:
        url = API + CFG["api"]["check_slot"]
        body = {
            "countryCode": CFG["portal"]["country_code"],
            "missionCode": CFG["portal"]["mission_code"],
            "vacCode": vac_code,
            "visaCategoryCode": visa_category_code,
            "roleName": "Individual",
            "loginUser": account_id,
            "payCode": "",
        }
        # Sadece authorize + content-type → 200. clientsource/route eklersen 409 yersin.
        r = await self.http.request("POST", url, identity=account_id, json_body=body)
        if not r:
            return None
        try:
            return r.json()
        except Exception:
            return None

    @staticmethod
    def slot_exists(payload: dict | None) -> bool:
        """200 içindeki error.code 1035 = 'slot yok'. Hata değil."""
        if not payload:
            return False
        err = payload.get("error") or {}
        if err.get("code") == 1035:
            return False
        return bool(payload.get("earliestDate"))

    # ---------- login + OTP ----------
    async def login_start(self, account_id: str, sifre: str) -> dict | None:
        url = API + CFG["api"]["login"]
        body = {
            "username": account_id,
            "password": sifre,
            "missionCode": CFG["portal"]["mission_code"],
            "countryCode": CFG["portal"]["country_code"],
            "cultureCode": CFG["portal"]["culture_code"],
        }
        r = await self.http.request("POST", url, identity=account_id, json_body=body)
        return r.json() if r else None

    async def login_otp(self, account_id: str, otp: str) -> dict | None:
        url = API + CFG["api"]["validate_otp"]
        body = {"username": account_id, "otpCode": otp, "otp": otp,
                "missionCode": CFG["portal"]["mission_code"]}
        r = await self.http.request("POST", url, identity=account_id, json_body=body)
        return r.json() if r else None

    @staticmethod
    def extract_otp(text: str) -> str | None:
        m = re.search(CFG["otp"]["regex"], text)
        return m.group(1) if m else None
bot/otp.py
python
"""IMAP OTP köprüsü. Hedefli SEARCH — tüm kutuyu taramaz."""
from __future__ import annotations
import asyncio
import email
import imaplib
import re
import time
from email.header import decode_header

from .config import CFG
from .db import DB


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else p for p, enc in parts)


class OtpBridge:
    def __init__(self, host: str, user: str, app_password: str):
        self.host = host or "imap.gmail.com"
        self.user = user
        self.password = app_password

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.host, int(CFG["otp"]["imap_port"]))
        conn.login(self.user, self.password)
        conn.select("INBOX", readonly=True)
        return conn

    def _search(self, conn: imaplib.IMAP4_SSL, since_ts: float) -> list[bytes]:
        since = time.strftime("%d-%b-%Y", time.localtime(since_ts))
        criteria = [f'(SINCE "{since}"']
        sender = CFG["otp"]["sender_filter"]
        if sender:
            criteria.append(f'FROM "{sender}"')
        subject_or = " OR ".join(f'SUBJECT "{s}"' for s in CFG["otp"]["subject_filter"])
        if subject_or:
            criteria.append(f"({subject_or})")
        query = " ".join(criteria) + ")"
        typ, data = conn.search(None, query)
        return data[0].split() if typ == "OK" and data and data[0] else []

    async def wait_for_otp(self, since_ts: float | None = None, timeout: float | None = None) -> str | None:
        """2 saniyede bir hedefli arama. IDLE'ın pratik karşılığı; daha az arıza noktası."""
        since_ts = since_ts or time.time() - 5
        timeout = timeout or float(CFG["otp"]["otp_timeout_s"])
        deadline = time.time() + timeout
        seen: set[bytes] = set()
        conn = None

        try:
            conn = await asyncio.to_thread(self._connect)
            while time.time() < deadline:
                ids = await asyncio.to_thread(self._search, conn, since_ts)
                for msg_id in reversed(ids):
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    typ, raw = await asyncio.to_thread(conn.fetch, msg_id, "(RFC822)")
                    if typ != "OK" or not raw or not raw[0]:
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += _decode(part.get_payload(decode=True).decode("utf-8", "ignore"))
                    else:
                        body = _decode(msg.get_payload(decode=True).decode("utf-8", "ignore"))
                    text = f"{_decode(msg.get('Subject', ''))} {body}"
                    otp = re.search(CFG["otp"]["regex"], text)
                    if otp:
                        DB.log("INFO", f"OTP yakalandı: {otp.group(1)}")
                        return otp.group(1)
                await asyncio.sleep(float(CFG["otp"]["poll_interval_s"]))
            DB.log("WARN", f"OTP {timeout:.0f}s içinde gelmedi")
            return None
        finally:
            if conn:
                try:
                    await asyncio.to_thread(conn.logout)
                except Exception:
                    pass
bot/excel_io.py
python
"""Excel = görünüm katmanı. Atomik yazma: tmp → os.replace."""
from __future__ import annotations
import asyncio
import os
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .config import CFG
from .db import DB, INPUT_COLS, OUTPUT_COLS

HEADERS = INPUT_COLS + OUTPUT_COLS


def read_inputs() -> list[dict]:
    path = Path(CFG["excel"]["path"])
    if not path.exists():
        return []
    wb = load_workbook(path, data_only=True)
    ws = wb[CFG["excel"]["sheet"]] if CFG["excel"]["sheet"] in wb.sheetnames else wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    header = [str(h).strip() if h else "" for h in rows[0]]
    out = []
    for raw in rows[1:]:
        row = {header[i]: raw[i] for i in range(min(len(header), len(raw))) if header[i] in INPUT_COLS}
        if row.get("id") and row.get("vfs_email"):
            out.append(row)
    return out


def write_outputs() -> None:
    """DB → Excel. Geçici dosyaya yaz, sonra atomik olarak yerine koy."""
    path = Path(CFG["excel"]["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = CFG["excel"]["sheet"]
    ws.append(HEADERS)
    for a in DB.applicants():
        ws.append([a.get(c) for c in HEADERS])

    wb.save(tmp)
    os.replace(tmp, path)  # atomik


def create_template() -> None:
    path = Path(CFG["excel"]["path"])
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = CFG["excel"]["sheet"]
    ws.append(HEADERS)
    ws.append([
        1, "AHMET", "YILMAZ", "U1234567", "1990-05-12", "TR", "+905550000000",
        "ornek@gmail.com", "", "gmail_uygulama_sifresi", "imap.gmail.com",
        "IST,ANK,EDR", "SCHENGEN", "2026-11-01", "2026-12-31", "", "PENDING",
    ])
    wb.save(path)


def sync_inputs_to_db() -> int:
    n = 0
    for row in read_inputs():
        DB.upsert_applicant(row)
        n += 1
    return n


async def excel_sync_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(sync_inputs_to_db)
            await asyncio.to_thread(write_outputs)
        except Exception as exc:
            DB.log("ERROR", f"excel sync: {exc}")
        await asyncio.sleep(float(CFG["excel"]["sync_interval_s"]))
bot/notify.py
python
"""Telegram: Bot API doğrudan. Inline buton + dedupe + heartbeat."""
from __future__ import annotations
import asyncio
import time

from curl_cffi.requests import AsyncSession

from .config import CFG
from .db import DB

_last: dict[str, float] = {}


class Notify:
    def __init__(self):
        self.token = CFG["telegram"]["token"]
        self.chat_id = CFG["telegram"]["chat_id"]
        self.base = f"https://api.telegram.org/bot{self.token}"

    async def send(self, text: str, keyboard: list | None = None, dedupe_key: str | None = None,
                   dedupe_s: float = 300) -> None:
        if not (self.token and self.chat_id):
            return
        if dedupe_key:
            if time.time() - _last.get(dedupe_key, 0) < dedupe_s:
                return
            _last[dedupe_key] = time.time()
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        async with AsyncSession(timeout=15) as s:
            try:
                await s.post(f"{self.base}/sendMessage", json=payload)
            except Exception as exc:
                DB.log("WARN", f"telegram gönderilemedi: {exc}")

    async def slot_alert(self, merkez: str, kategori: str, tarih: str, applicant_id: int) -> None:
        key = f"slot:{merkez}:{kategori}:{tarih}:{applicant_id}"
        await self.send(
            f"<b>SLOT AÇILDI</b>\nMerkez: {merkez}\nKategori: {kategori}\n"
            f"Tarih: {tarih}\nBaşvuran #{applicant_id}",
            keyboard=[[
                {"text": "Rezerve Et", "callback_data": f"book:{applicant_id}"},
                {"text": "Yoksay", "callback_data": f"skip:{applicant_id}"},
            ]],
            dedupe_key=key,
        )

    async def heartbeat(self) -> None:
        aktif = len(DB.applicants(durum=("PENDING", "SESSION_ACTIVE", "POLLING_SLOTS")))
        await self.send(
            f"<b>Bot ayakta</b>\nİzlenen başvuran: {aktif}\n"
            f"Son slot kaydı: {DB.meta_get('son_slot', '-')}",
            dedupe_key="heartbeat",
        )

    async def heartbeat_loop(self) -> None:
        while True:
            await self.heartbeat()
            await asyncio.sleep(float(CFG["telegram"]["heartbeat_s"]))
bot/poller.py
python
"""Katman 0: login'siz public sweep. Slot tespitinin tamamı burada çözülür."""
from __future__ import annotations
import asyncio
import random
import time
from datetime import datetime

from .config import CFG
from .db import DB
from .http import VfsHttp
from .notify import Notify
from .vfs import VfsClient

DATE_FORMATS = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d"]


def parse_date(value: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def in_window(tarih: str, bas: str, bit: str) -> bool:
    d = parse_date(tarih)
    if not d:
        return False
    try:
        return datetime.fromisoformat(bas) <= d <= datetime.fromisoformat(bit)
    except ValueError:
        return True


def night_multiplier() -> float:
    nw = CFG["polling"]["night_window"]
    now = time.strftime("%H:%M")
    return float(CFG["polling"]["night_multiplier"]) if nw[0] <= now <= nw[1] else 1.0


class PublicPoller:
    """Tek cf_clearance yeter. Hesap kilidi riski sıfır, OTP yok."""

    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    async def sweep_once(self) -> int:
        data = await self.vfs.public_earliest()
        rows = self.vfs.parse_public(data)
        if data:
            DB.meta_set("son_sweep", DB.now())
            DB.meta_set("public_last_updated", str(data.get("lastUpdatedOn", "")))
        hits = 0

        bekleyen = DB.applicants(durum=("PENDING", "SESSION_ACTIVE", "POLLING_SLOTS"))
        for row in rows:
            for ap in bekleyen:
                tercihler = [t.strip() for t in (ap["merkez_tercih"] or "").split(",") if t.strip()]
                if tercihler and not any(t.lower() in row["merkez"].lower() for t in tercihler):
                    continue
                if not in_window(row["tarih"], ap["tarih_baslangic"] or "", ap["tarih_bitis"] or ""):
                    continue
                h = self.vfs.slot_hash(row["merkez"], row["kategori"], row["tarih"])
                if not DB.slot_is_new(h, row["merkez"], row["kategori"], row["tarih"]):
                    continue
                hits += 1
                DB.meta_set("son_slot", f"{row['merkez']} {row['kategori']} {row['tarih']} @ {DB.now()}")
                DB.log("SLOT", f"{row['merkez']} / {row['kategori']} / {row['tarih']}", ap["id"])
                await self.notify.slot_alert(row["merkez"], row["kategori"], row["tarih"], ap["id"])
        return hits

    async def run(self) -> None:
        DB.log("INFO", "PublicPoller başladı")
        while True:
            try:
                await self.sweep_once()
            except Exception as exc:
                DB.log("ERROR", f"public sweep: {exc}")
            lo, hi = CFG["polling"]["public_interval_s"]
            await asyncio.sleep(random.uniform(lo, hi) * night_multiplier())
bot/booker.py — iskelet (recon ile doldurulacak)
python
"""Katman 1: login → CheckIsSlotAvailable → POST rezervasyon. Hedef: slot gördükten sonra <5 sn."""
from __future__ import annotations
import time

from .config import CFG
from .db import DB
from .http import VfsHttp
from .notify import Notify
from .otp import OtpBridge
from .vfs import VfsClient


class LoginWorker:
    """Login en pahalı işlem: hesap başına 3 deneme bütçesi, sonra 30 dk dinlenme."""

    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    async def ensure_session(self, ap) -> bool:
        account_id = ap["vfs_email"]
        s = DB.session_load(account_id)

        # 1) Geçerli oturum varsa login'e hiç dokunma (24 saat kilidine karşı en önemli kural)
        if s and s.get("authorize"):
            return True

        # 2) Bütçe kontrolü
        budget_key = f"login_budget:{account_id}"
        if DB.proxy_cooling(budget_key):
            return False

        otp_bridge = OtpBridge(ap["imap_sunucu"], account_id, ap["imap_app_sifre"])
        for deneme in range(int(CFG["session"]["login_budget"])):
            since = time.time()
            if not await self.vfs.login_start(account_id, ap["vfs_sifre"]):
                continue
            otp = await otp_bridge.wait_for_otp(since_ts=since)
            if not otp:
                DB.log("WARN", f"OTP gelmedi (deneme {deneme + 1}): {account_id}")
                continue
            result = await self.vfs.login_otp(account_id, otp)
            if result and not (result.get("error") or {}).get("code"):
                # authorize JWT'sini burada session'a yaz — recon sonrası teyit edilecek
                DB.session_save(account_id, authorize=result.get("jwt") or result.get("token"))
                DB.log("INFO", f"Oturum açıldı: {account_id}")
                return True

        DB.proxy_penalize(budget_key, float(CFG["session"]["login_cooldown_s"]))
        await self.notify.send(f"<b>Login başarısız</b> ({account_id}) → 30 dk dinlenme. MANUAL_REVIEW.")
        DB.log("WARN", f"login bütçesi tükendi: {account_id}")
        return False


class Booker:
    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    def build_payload(self, ap) -> dict:
        """Slot bulunduğu ANDA çalışacak hazır gövde. Recon ile alan adları teyit edilecek."""
        return {
            "countryCode": CFG["portal"]["country_code"],
            "missionCode": CFG["portal"]["mission_code"],
            "vacCode": ap["merkez"],
            "visaCategoryCode": ap["kategori"],
            "roleName": "Individual",
            "loginUser": ap["vfs_email"],
            "applicant": {
                "firstName": ap["ad"],
                "lastName": ap["soyad"],
                "passportNumber": ap["pasaport_no"],
                "dateOfBirth": ap["dogum_tarihi"],
                "nationality": ap["uyruk"],
                "contactNumber": ap["telefon"],
                "email": ap["vfs_email"],
            },
        }

    async def book(self, ap, tarih: str) -> bool:
        t0 = time.perf_counter()
        r = await self.http.request(
            "POST", CFG["api"]["base"].rstrip("/") + CFG["api"]["book"],
            identity=ap["vfs_email"], json_body=self.build_payload(ap),
        )
        if not r:
            DB.bump_attempt(ap["id"], "booking isteği başarısız")
            return False
        try:
            data = r.json()
        except Exception:
            data = {}

        ref = (data.get("referenceNumber") or data.get("refNo")
               or (data.get("data") or {}).get("referenceNumber"))
        if not ref:
            DB.bump_attempt(ap["id"], str(data)[:400])
            return False

        DB.set_status(ap["id"], "BOOKED", randevu_tarihi=tarih, referans_no=ref, son_hata="")
        DB.log("BOOKED", f"referans {ref} / {time.perf_counter() - t0:.2f}s", ap["id"])
        await self.notify.send(
            f"<b>RANDEVU ALINDI</b>\n{ap['ad']} {ap['soyad']}\nTarih: {tarih}\nReferans: <code>{ref}</code>"
        )
        return True
bot/main.py
python
from __future__ import annotations
import asyncio
import logging
import sys

from .config import CFG
from .db import DB
from .excel_io import create_template, excel_sync_loop
from .http import VfsHttp
from .notify import Notify
from .poller import PublicPoller
from .proxy import ProxyManager
from .vfs import VfsClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def amain() -> None:
    if not CFG["proxy"]["isp_pool"]:
        logging.warning("proxy.isp_pool boş — datacenter IP'de 403201 alman çok muhtemel.")

    proxy_mgr = ProxyManager()
    http = VfsHttp(proxy_mgr)
    vfs = VfsClient(http)
    notify = Notify()

    DB.log("INFO", "bot başladı")
    await notify.send("<b>VFS bot başladı</b>\nMod: public sweep (Katman 0)")

    try:
        await asyncio.gather(
            excel_sync_loop(),
            PublicPoller(http, vfs, notify).run(),
            notify.heartbeat_loop(),
        )
    finally:
        await http.close()


def cli() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "template":
        create_template()
        print(f"Şablon oluşturuldu: {CFG['excel']['path']}")
        return
    asyncio.run(amain())


if __name__ == "__main__":
    cli()
scripts/recon.py — ilk çalıştıracağın şey
python
"""Recon: cf_clearance üret, x-auth-token topla, endpoint'leri yokla, hazır curl bas."""
import asyncio, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from curl_cffi.requests import AsyncSession
from bot.config import CFG
from bot.http import VfsHttp
from bot.proxy import ProxyManager

API = CFG["api"]["base"].rstrip("/")
PROBES = [
    ("POST", CFG["api"]["public_earliest"],
     {"missionCode": CFG["portal"]["mission_code"], "countryCode": CFG["portal"]["country_code"],
      "cultureCode": CFG["portal"]["culture_code"]}, {"x-auth-token": CFG["portal"]["x_auth_token"]}),
    ("POST", CFG["api"]["check_slot"],
     {"countryCode": CFG["portal"]["country_code"], "missionCode": CFG["portal"]["mission_code"],
      "vacCode": CFG["centres"][0]["code"], "visaCategoryCode": CFG["categories"][0]["code"],
      "roleName": "Individual", "loginUser": "", "payCode": ""}, {}),
]


async def harvest_token(proxy: str) -> str | None:
    from playwright.async_api import async_playwright
    found: list[str] = []
    kwargs = {"channel": "chrome", "headless": True}
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    async with async_playwright() as p:
        browser = await p.chromium.launch(**kwargs)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.on("request", lambda r: found.append(r.headers.get("x-auth-token", ""))
                if "lift-api" in r.url else None)
        await page.goto(CFG["portal"]["base"], wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(12)
        await browser.close()
    return next((t for t in found if t), None)


async def main() -> None:
    proxy = CFG["proxy"]["isp_pool"][0] if CFG["proxy"]["isp_pool"] else ""
    http = VfsHttp(ProxyManager())

    print("1) cf_clearance üretiliyor...")
    ok = await http.ensure_cf_clearance("public", proxy)
    print(f"   cf_clearance: {'OK' if ok else 'BAŞARISIZ'}")

    print("2) x-auth-token toplanıyor...")
    token = await harvest_token(proxy)
    print(f"   x-auth-token: {token or 'bulunamadı'} → config.yaml'a yaz")

    print("3) endpoint yoklaması:")
    for method, path, body, headers in PROBES:
        r = await http.request(method, API + path, identity="public", json_body=body, headers=headers)
        status = r.status_code if r else "YOK"
        print(f"   {method} {path} → {status}")
        if r:
            print(f"      {r.text[:400]}")

    print("4) login endpoint şekli (Playwright ağ kaydı ile teyit edilecek):")
    print(json.dumps({"login": CFG["api"]["login"], "otp": CFG["api"]["validate_otp"]}, indent=2))

    await http.close()


if __name__ == "__main__":
    asyncio.run(main())
docker-compose.yml
yaml
services:
  vfsbot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config.yaml:/app/config.yaml
    shm_size: 1gb          # Chrome için
    command: python -m bot.main

  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:latest
    restart: unless-stopped
    environment:
      LOG_LEVEL: warning
    ports:
      - "8191:8191"
Dockerfile
dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates fonts-liberation \
 && wget -qO- https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor > /usr/share/keyrings/google.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google.list \
 && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install --with-deps chromium
COPY . .
CMD ["python", "-m", "bot.main"]
Şimdi sırayla yapılacaklar
bash
pip install -r requirements.txt && playwright install chromium
python -m bot.main template          # Excel şablonunu üret, doldur
export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
python scripts/recon.py              # cf_clearance + x-auth-token + endpoint teyidi
Recon çıktısı bize üç şeyi verir: x-auth-token değeri, public_earliest'ın 200 dönüp dönmediği, ve login/OTP/booking endpoint'lerinin gerçek şekli. Ondan sonra booker.py içindeki payload alanlarını kesinleştiririz.