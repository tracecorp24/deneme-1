"""
VFS Vize Botu - Yapılandırma Dosyası
Hedef Portal: Türkiye -> Bulgaristan (https://visa.vfsglobal.com/tur/en/bgr/)
"""
import os
from pathlib import Path

# Temel Dizinler
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "chrome_profile"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"

for d in [DATA_DIR, PROFILE_DIR, SESSIONS_DIR, LOGS_DIR, SCREENSHOTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Hedef Portal URL'leri (plan.md Bölüm 2 ve Bölüm 13)
PORTAL_COUNTRY = "tur"
PORTAL_LANG = "en"
PORTAL_MISSION = "bgr"

BASE_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/"
APPOINTMENT_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/book-an-appointment"
LOGIN_URL = f"https://visa.vfsglobal.com/{PORTAL_COUNTRY}/{PORTAL_LANG}/{PORTAL_MISSION}/login"

# Tarayıcı Yapılandırması
BROWSER_CONFIG = {
    "headless": False,  # Turnstile ve Cloudflare güvenliği için False (üretimde Xvfb/ekran ile çalışabilir)
    "channel": "chrome",  # Makinede yüklü gerçek Google Chrome ikilisi
    "user_data_dir": str(PROFILE_DIR),
    "viewport": None,  # Tam ekran / doğal çözünürlük
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

# İnsansı Davranış ve Zamanlama Parametreleri (Anti-Ban & Jitter)
HUMAN_CONFIG = {
    # Beklemelerdeki rastgele sapma yüzdesi (Jitter)
    "jitter_pct": 0.25,
    
    # Fare hareket hızları (piksel/adım)
    "mouse_step_divisor": 14,
    "mouse_min_steps": 22,
    "mouse_micro_delay_min": 0.005,
    "mouse_micro_delay_max": 0.016,
    
    # Tıklama süreleri (mouse down -> mouse up)
    "click_hold_min": 0.075,
    "click_hold_max": 0.145,
    
    # Hover dwell (tıklamadan önce buton üzerinde bekleme)
    "hover_dwell_min": 0.25,
    "hover_dwell_max": 0.55,
    
    # Klavye tuş basımı gecikmesi (saniye)
    "typing_delay_min": 0.065,
    "typing_delay_max": 0.160,
    "typing_special_pause_min": 0.180,
    "typing_special_pause_max": 0.350,
}

# Captcha / Turnstile Zaman Aşımları
CAPTCHA_CONFIG = {
    "turnstile_max_wait_seconds": 30,
    "poll_interval_seconds": 1.0,
}
