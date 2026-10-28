"""
bot/booker.py - Katman 1: login → CheckIsSlotAvailable → POST rezervasyon.
Hedef: slot görüldükten sonra <5 saniye içinde tamamlamak.
"""
from __future__ import annotations
import time
from typing import Any

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

    async def ensure_session(self, ap: Any) -> bool:
        account_id = ap["vfs_email"]
        s = DB.session_load(account_id)

        # 1) Geçerli oturum varsa login'e hiç dokunma (24 saat kilidine karşı en önemli kural)
        if s and s.get("authorize"):
            return True

        # 2) Bütçe kontrolü
        budget_key = f"login_budget:{account_id}"
        if DB.proxy_cooling(budget_key):
            DB.log("WARN", f"Login bütçesi beklemede (cooldown): {account_id}")
            return False

        if not ap["imap_app_sifre"]:
            DB.log("WARN", f"IMAP uygulama şifresi eksik: {account_id}")
            return False

        otp_bridge = OtpBridge(ap["imap_sunucu"] or "imap.gmail.com", account_id, ap["imap_app_sifre"])
        for deneme in range(int(CFG["session"]["login_budget"])):
            since = time.time()
            DB.log("INFO", f"VFS Login başlatılıyor (deneme {deneme + 1}): {account_id}")
            
            res_start = await self.vfs.login_start(account_id, ap["vfs_sifre"])
            if not res_start:
                continue

            DB.log("INFO", f"OTP kodu e-postadan bekleniyor (IMAP): {account_id}")
            otp = await otp_bridge.wait_for_otp(since_ts=since)
            if not otp:
                DB.log("WARN", f"OTP gelmedi (deneme {deneme + 1}): {account_id}")
                continue

            DB.log("INFO", f"OTP yakalandı ({otp}), VFS'e iletiliyor...")
            result = await self.vfs.login_otp(account_id, otp)
            if result and not (result.get("error") or {}).get("code"):
                token = result.get("jwt") or result.get("token") or result.get("accessToken")
                DB.session_save(account_id, authorize=token)
                DB.log("SUCCESS", f"Oturum başarıyla açıldı (JWT alındı): {account_id}")
                return True

        DB.proxy_penalize(budget_key, float(CFG["session"]["login_cooldown_s"]))
        await self.notify.send(f"⚠️ <b>Login başarısız</b> ({account_id}) → 30 dk dinlenme uygulandı.")
        DB.log("WARN", f"Login bütçesi tükendi: {account_id}")
        return False


class Booker:
    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    def build_payload(self, ap: Any, slot_details: dict | None = None) -> dict:
        """Slot bulunduğu ANDA çalışacak hazır gövde."""
        center_code = (ap["merkez_tercih"] or "IST").split(",")[0].strip()
        category_code = ap["kategori"] or "SCHENGEN"

        return {
            "countryCode": CFG["portal"]["country_code"],
            "missionCode": CFG["portal"]["mission_code"],
            "vacCode": slot_details.get("vacCode") if slot_details else center_code,
            "visaCategoryCode": slot_details.get("visaCategoryCode") if slot_details else category_code,
            "roleName": "Individual",
            "loginUser": ap["vfs_email"],
            "applicant": {
                "firstName": ap["ad"],
                "lastName": ap["soyad"],
                "passportNumber": ap["pasaport_no"],
                "dateOfBirth": ap["dogum_tarihi"],
                "nationality": ap["uyruk"] or "TUR",
                "contactNumber": ap["telefon"],
                "email": ap["vfs_email"],
            },
        }

    async def book(self, ap: Any, tarih: str, slot_details: dict | None = None) -> bool:
        t0 = time.perf_counter()
        url = CFG["api"]["base"].rstrip("/") + CFG["api"]["book"]
        payload = self.build_payload(ap, slot_details)

        DB.log("INFO", f"Rezervasyon POST isteği gönderiliyor: {ap['ad']} {ap['soyad']} -> {tarih}")
        r = await self.http.request(
            "POST", url,
            identity=ap["vfs_email"], json_body=payload,
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
            err_msg = str(data)[:400]
            DB.bump_attempt(ap["id"], err_msg)
            DB.log("ERROR", f"Rezervasyon onaylanamadı: {err_msg}", ap["id"])
            return False

        duration = time.perf_counter() - t0
        DB.set_status(ap["id"], "BOOKED", randevu_tarihi=tarih, referans_no=ref, son_hata="")
        DB.log("BOOKED", f"RANDEVU ALINDI! Referans: {ref} ({duration:.2f} sn)", ap["id"])
        
        await self.notify.send(
            f"🎉 <b>RANDEVU BAŞARIYLA ALINDI!</b>\n"
            f"👤 <b>Başvuran:</b> {ap['ad']} {ap['soyad']}\n"
            f"📅 <b>Tarih:</b> {tarih}\n"
            f"🔖 <b>Referans No:</b> <code>{ref}</code>\n"
            f"⚡ <b>İşlem Süresi:</b> {duration:.2f} saniye"
        )
        return True
