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
    raw = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

    raw.setdefault("portal", {})
    raw["portal"].setdefault("base", "https://visa.vfsglobal.com/tur/en/bgr")
    raw["portal"].setdefault("country_code", "tur")
    raw["portal"].setdefault("mission_code", "bgr")
    raw["portal"].setdefault("culture_code", "en-US")
    raw["portal"].setdefault("login_path", "/login")
    raw["portal"].setdefault("x_auth_token", "")

    raw.setdefault("api", {})
    raw["api"].setdefault("base", "https://lift-api.vfsglobal.com")
    raw["api"].setdefault("public_earliest", "/appointment/centerwithearliestslot")
    raw["api"].setdefault("check_slot", "/appointment/CheckIsSlotAvailable")
    raw["api"].setdefault("login", "/user/login")
    raw["api"].setdefault("validate_otp", "/user/validateotp")
    raw["api"].setdefault("book", "/appointment/bookappointment")

    raw.setdefault("http", {})
    raw["http"].setdefault("impersonate", "chrome")
    raw["http"].setdefault("timeout_s", 25)
    raw["http"].setdefault("per_ip_concurrency", 3)
    raw["http"].setdefault("max_retries", 3)

    raw.setdefault("polling", {})
    raw["polling"].setdefault("public_interval_s", [300, 480])
    raw["polling"].setdefault("delay_honor_margin_s", 3)
    raw["polling"].setdefault("night_window", ["02:00", "05:00"])
    raw["polling"].setdefault("night_multiplier", 2.0)

    raw.setdefault("session", {})
    raw["session"].setdefault("cf_clearance_ttl_s", 1500)
    raw["session"].setdefault("login_budget", 3)
    raw["session"].setdefault("login_cooldown_s", 1800)

    raw.setdefault("proxy", {})
    raw["proxy"].setdefault("isp_pool", [])
    raw["proxy"].setdefault("health_cooldown_s", 900)

    raw.setdefault("otp", {})
    raw["otp"].setdefault("imap_port", 993)
    raw["otp"].setdefault("sender_filter", "vfsglobal")
    raw["otp"].setdefault("subject_filter", ["OTP", "verification", "code", "One Time Password"])
    raw["otp"].setdefault("poll_interval_s", 2)
    raw["otp"].setdefault("otp_timeout_s", 85)
    raw["otp"].setdefault("regex", "\\b(\\d{6})\\b")

    raw.setdefault("excel", {})
    raw["excel"].setdefault("path", "data/basvuranlar.xlsx")
    raw["excel"].setdefault("sheet", "Applicants")
    raw["excel"].setdefault("sync_interval_s", 30)

    raw.setdefault("telegram", {})
    raw["telegram"]["token"] = os.getenv("TELEGRAM_TOKEN", raw["telegram"].get("token", ""))
    raw["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID", raw["telegram"].get("chat_id", ""))
    raw["telegram"].setdefault("heartbeat_s", 600)

    raw.setdefault("paths", {})
    for key, default in (("data_dir", "data"), ("session_dir", "data/sessions"), ("log_dir", "logs")):
        raw["paths"][key] = str(ROOT / raw["paths"].get(key, default))
        Path(raw["paths"][key]).mkdir(parents=True, exist_ok=True)

    return Cfg(raw)


CFG = load_config()
