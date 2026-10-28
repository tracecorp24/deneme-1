"""
VFS Vize Botu - Aşama 1 Teşhis ve Tarayıcı Yapılandırma Dosyası
core/ modülü sadece Aşama 1 teşhisi (tarayıcı testi, Turnstile ve ısınma) için kullanılır; bot/ modülü üretimdir.
"""
import os
from pathlib import Path

# Temel Dizinler (proje köküne göre)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "chrome_profile"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"

for d in [DATA_DIR, PROFILE_DIR, SESSIONS_DIR, LOGS_DIR, SCREENSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Hedef Portal URL'leri
PORTAL_COUNTRY = "tur"
PORTAL_LANG = "en"
PORTAL_MISSION = "bgr"

BASE_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/"
APPOINTMENT_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/book-an-appointment"
LOGIN_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/login"

# Tarayıcı Yapılandırması
BROWSER_CONFIG = {
    "headless": False,
    "channel": "chrome",
    "user_data_dir": str(PROFILE_DIR),
    "viewport": None,
    "locale": "tr-TR",
    "timezone_id": "Europe/Istanbul",
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--lang=tr-TR,tr,en-US,en",
    ]
}

# İnsansı Davranış ve Zamanlama Parametreleri
HUMAN_CONFIG = {
    "jitter_pct": 0.25,
    "mouse_step_divisor": 14,
    "mouse_min_steps": 22,
    "mouse_micro_delay_min": 0.005,
    "mouse_micro_delay_max": 0.016,
    "click_hold_min": 0.075,
    "click_hold_max": 0.145,
    "hover_dwell_min": 0.25,
    "hover_dwell_max": 0.55,
    "typing_delay_min": 0.065,
    "typing_delay_max": 0.160,
    "typing_special_pause_min": 0.180,
    "typing_special_pause_max": 0.350,
}

# Turnstile & Captcha Parametreleri
CAPTCHA_CONFIG = {
    "turnstile_iframe_selector": "iframe[src*='challenges.cloudflare.com']",
    "turnstile_box_selector": "body",
    "poll_interval_sec": 0.3,
    "max_retries": 3,
}
