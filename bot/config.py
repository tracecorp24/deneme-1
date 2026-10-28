from __future__ import annotations
import os
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

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
    # 1. .env dosyasını yükle
    load_dotenv(ROOT / ".env")

    raw = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    # Portal Ayarları
    raw.setdefault("portal", {})
    raw["portal"].setdefault("base", "https://visa.vfsglobal.com/tur/en/bgr")
    raw["portal"].setdefault("country_code", "tur")
    raw["portal"].setdefault("mission_code", "bgr")
    raw["portal"].setdefault("culture_code", "en-US")
    raw["portal"].setdefault("login_path", "/login")
    
    # A2: x_auth_token env override
    raw["portal"]["x_auth_token"] = os.getenv(
        "VFS_X_TOKEN", 
        os.getenv("PORTAL_X_AUTH_TOKEN", raw["portal"].get("x_auth_token", ""))
    ).strip()

    # API Endpoints
    raw.setdefault("api", {})
    raw["api"].setdefault("base", "https://lift-api.vfsglobal.com")
    raw["api"].setdefault("public_earliest", "/appointment/centerwithearliestslot")
    raw["api"].setdefault("check_slot", "/appointment/CheckIsSlotAvailable")
    raw["api"].setdefault("login", "/user/login")
    raw["api"].setdefault("validate_otp", "/user/validateotp")
    raw["api"].setdefault("book", "/appointment/bookappointment")

    # HTTP & Tarayıcı Ayarları
    raw.setdefault("http", {})
    raw["http"].setdefault("impersonate", "chrome")
    raw["http"].setdefault("timeout_s", 25)
    raw["http"].setdefault("per_ip_concurrency", 3)
    raw["http"].setdefault("max_retries", 3)
    
    # A2: http.headless env override
    env_headless = os.getenv("VFS_HEADLESS")
    if env_headless is not None:
        raw["http"]["headless"] = env_headless.strip().lower() in ("true", "1", "yes")
    else:
        raw["http"].setdefault("headless", False)

    # Polling Ayarları
    raw.setdefault("polling", {})
    raw["polling"].setdefault("public_interval_s", [300, 480])
    raw["polling"].setdefault("delay_honor_margin_s", 3)
    raw["polling"].setdefault("night_window", ["02:00", "05:00"])
    raw["polling"].setdefault("night_multiplier", 2.0)

    # Oturum Ayarları
    raw.setdefault("session", {})
    raw["session"].setdefault("cf_clearance_ttl_s", 1500)
    raw["session"].setdefault("login_budget", 3)
    raw["session"].setdefault("login_cooldown_s", 1800)

    # Proxy Havuzu
    raw.setdefault("proxy", {})
    raw["proxy"].setdefault("health_cooldown_s", 900)
    
    # A2: proxy.isp_pool env override (virgülle ayrılmış)
    env_proxies = os.getenv("VFS_PROXIES", os.getenv("PROXY_ISP_POOL"))
    if env_proxies:
        raw["proxy"]["isp_pool"] = [p.strip() for p in env_proxies.split(",") if p.strip()]
    else:
        raw["proxy"].setdefault("isp_pool", [])

    # OTP Ayarları
    raw.setdefault("otp", {})
    raw["otp"]["imap_port"] = int(os.getenv("OTP_IMAP_PORT", raw["otp"].get("imap_port", 993)))
    raw["otp"]["sender_filter"] = os.getenv("OTP_SENDER", raw["otp"].get("sender_filter", "vfsglobal"))
    raw["otp"].setdefault("subject_filter", ["OTP", "verification", "code", "One Time Password"])
    raw["otp"].setdefault("poll_interval_s", 2)
    raw["otp"].setdefault("otp_timeout_s", 85)
    raw["otp"]["regex"] = os.getenv("OTP_REGEX", raw["otp"].get("regex", "\\b(\\d{6})\\b"))

    # Excel Ayarları
    raw.setdefault("excel", {})
    raw["excel"]["path"] = os.getenv("EXCEL_PATH", raw["excel"].get("path", "data/basvuranlar.xlsx"))
    raw["excel"].setdefault("sheet", "Applicants")
    raw["excel"].setdefault("sync_interval_s", 30)

    # Telegram Ayarları
    raw.setdefault("telegram", {})
    raw["telegram"]["token"] = os.getenv("TELEGRAM_TOKEN", raw["telegram"].get("token", "")).strip()
    raw["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", raw["telegram"].get("chat_id", "")).strip()
    raw["telegram"].setdefault("heartbeat_s", 600)

    # Rezervasyon Ayarları
    raw.setdefault("booking", {})
    env_autobook = os.getenv("AUTO_BOOK")
    if env_autobook is not None:
        raw["booking"]["auto_book"] = env_autobook.strip().lower() in ("true", "1", "yes")
    else:
        raw["booking"].setdefault("auto_book", False)
    raw["booking"].setdefault("preferred_hour", "morning")

    # Dizin Yolları
    raw.setdefault("paths", {})
    for key, default in (("data_dir", "data"), ("session_dir", "data/sessions"), ("log_dir", "logs")):
        raw["paths"][key] = str(ROOT / raw["paths"].get(key, default))
        Path(raw["paths"][key]).mkdir(parents=True, exist_ok=True)

    return Cfg(raw)


CFG = load_config()
