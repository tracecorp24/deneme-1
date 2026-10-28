"""
bot/vfs.py - VFS'e özel iş mantığı ve API çağrı katmanı.
"""
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

    # ---------- KATMAN 0: login gerektirmez (Public Sweep) ----------
    async def public_earliest(self) -> dict | None:
        url = API + CFG["api"]["public_earliest"]
        body = {
            "missionCode": CFG["portal"]["mission_code"],
            "countryCode": CFG["portal"]["country_code"],
            "cultureCode": CFG["portal"]["culture_code"],
        }
        headers = {}
        if CFG["portal"]["x_auth_token"]:
            token_val = CFG["portal"]["x_auth_token"].strip()
            token_hdr = (CFG["portal"].get("token_header") or "authorization").strip().lower()
            if token_hdr == "authorization":
                if not token_val.lower().startswith("bearer "):
                    token_val = f"Bearer {token_val}"
                headers["authorization"] = token_val
            elif token_hdr in ("x-auth-token", "x_auth_token"):
                if token_val.lower().startswith("bearer "):
                    token_val = token_val[7:].strip()
                headers["x-auth-token"] = token_val
            else:
                headers[token_hdr] = token_val

        r = await self.http.request(
            "POST", url, identity="public", json_body=body,
            headers=headers,
        )
        if not r:
            return None
        if r.status_code != 200:
            DB.log("WARN", f"public_earliest HTTP {r.status_code}: {r.text[:120]}")
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

    # ---------- KATMAN 1: login gerekir (Slot Doğrulama + Rezervasyon) ----------
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
        if str(err.get("code")) == "1035":
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
        body = {
            "username": account_id,
            "otpCode": otp,
            "missionCode": CFG["portal"]["mission_code"]
        }
        r = await self.http.request("POST", url, identity=account_id, json_body=body)
        return r.json() if r else None

    @staticmethod
    def extract_otp(text: str) -> str | None:
        m = re.search(CFG["otp"]["regex"], text)
        return m.group(1) if m else None
