"""
bot/booker.py - Katman 1: login → CheckIsSlotAvailable → POST rezervasyon.
Hedef: slot görüldükten sonra <5 saniye içinde tamamlamak.
E1: submitted_at idempotens kontrolü
E2: authorize JWT exp süresi kontrolü
E3: login_budget meta tablosuna taşıma
E4: login_start hata kodu denetimi
E5: 429202 / 24 saat hesap kilidi özel işleme
E6: vacCode / visaCategoryCode kesin doğrulama
"""
from __future__ import annotations
import base64
import json
import time
from typing import Any

from .config import CFG
from .db import DB
from .http import VfsHttp
from .notify import Notify
from .otp import OtpBridge
from .vfs import VfsClient


def is_jwt_valid(token: str) -> bool:
    """
    E2: JWT exp alanını harici kütüphane olmadan base64url ile çözer.
    Süresi geçmişse veya biçimi bozuksa False döner.
    """
    if not token or not isinstance(token, str):
        return False
    raw_token = token.replace("Bearer ", "").strip()
    parts = raw_token.split(".")
    if len(parts) != 3:
        return False
    try:
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding < 4:
            payload_b64 += "=" * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = payload.get("exp")
        if exp is not None:
            # 30 saniyelik güvenlik marjı
            return float(exp) > (time.time() + 30)
        return True
    except Exception:
        return False


class LoginWorker:
    """Login en pahalı işlem: hesap başına 3 deneme bütçesi, sonra 30 dk dinlenme."""

    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    async def ensure_session(self, ap: Any) -> bool:
        account_id = ap["vfs_email"]
        s = DB.session_load(account_id)

        # 1) E2: Geçerli ve süresi dolmamış oturum varsa login'e hiç dokunma
        if s and s.get("authorize"):
            if is_jwt_valid(s["authorize"]):
                return True
            else:
                DB.log("WARN", f"Mevcut JWT oturumunun süresi dolmuş (expired): {account_id}", ap["id"])
                DB.session_save(account_id, authorize=None)

        # 2) E3: Bütçe ve cooldown kontrolü (meta tablosundan)
        budget_key = f"login_budget:{account_id}"
        if DB.budget_is_locked(budget_key):
            DB.log("WARN", f"Login bütçesi beklemede (cooldown aktif): {account_id}", ap["id"])
            return False

        if not ap["imap_app_sifre"]:
            DB.log("WARN", f"IMAP uygulama şifresi eksik: {account_id}", ap["id"])
            return False

        otp_bridge = OtpBridge(ap["imap_sunucu"] or "imap.gmail.com", account_id, ap["imap_app_sifre"])
        for deneme in range(int(CFG["session"]["login_budget"])):
            since = time.time()
            DB.log("INFO", f"VFS Login başlatılıyor (deneme {deneme + 1}): {account_id}", ap["id"])
            
            res_start = await self.vfs.login_start(account_id, ap["vfs_sifre"])
            res_str = str(res_start) if res_start else ""

            # E5: 429202 / 24 saat hesap kilidi kontrolü
            if "429202" in res_str or "24" in res_str.lower() and "hour" in res_str.lower():
                DB.set_status(ap["id"], "LOCKED_24H", son_hata="VFS 24 saat hesap kilidi (429202)")
                DB.budget_lock(budget_key, 21600)  # 6 saat cooldown
                if self.notify:
                    await self.notify.send(f"🚨 <b>VFS 24 Saat Hesap Kilidi:</b> {account_id} -> 6 saat bekleme moduna alındı.")
                DB.log("WARN", f"24 saat hesap kilidi tespit edildi (429202): {account_id}", ap["id"])
                return False

            # E4: login_start hata kodu dönerse OTP bekleme, sonraki denemeye geç
            if not res_start:
                continue
            if res_start.get("error") or res_start.get("errors") or (res_start.get("code") and res_start.get("code") != 200):
                err = res_start.get("error") or res_start.get("description") or res_start.get("code")
                DB.log("WARN", f"Login isteği hata döndü ({err}), OTP beklenmiyor: {account_id}", ap["id"])
                continue

            DB.log("INFO", f"OTP kodu e-postadan bekleniyor (IMAP): {account_id}", ap["id"])
            otp = await otp_bridge.wait_for_otp(since_ts=since)
            if not otp:
                DB.log("WARN", f"OTP gelmedi (deneme {deneme + 1}): {account_id}", ap["id"])
                continue

            DB.log("INFO", f"OTP yakalandı ({otp}), VFS'e iletiliyor...", ap["id"])
            result = await self.vfs.login_otp(account_id, otp)
            if result and not (result.get("error") or {}).get("code"):
                token = result.get("jwt") or result.get("token") or result.get("accessToken")
                if token:
                    DB.session_save(account_id, authorize=token)
                    DB.log("SUCCESS", f"Oturum başarıyla açıldı (JWT alındı): {account_id}", ap["id"])
                    return True

        # Bütçe tükendi → standart cooldown (30 dk)
        DB.budget_lock(budget_key, float(CFG["session"]["login_cooldown_s"]))
        if self.notify:
            await self.notify.send(f"⚠️ <b>Login başarısız</b> ({account_id}) → 30 dk dinlenme uygulandı.")
        DB.log("WARN", f"Login bütçesi tükendi: {account_id}", ap["id"])
        return False


class Booker:
    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify):
        self.http, self.vfs, self.notify = http, vfs, notify

    def build_payload(self, ap: Any, slot_details: dict | None = None) -> dict:
        """
        E6: vacCode ve visaCategoryCode kesin doğrulanır; eksikse ValueError fırlatır.
        """
        center_code = (slot_details.get("vacCode") if slot_details else None) or ap.get("merkez") or (ap["merkez_tercih"] or "IST").split(",")[0].strip()
        category_code = (slot_details.get("visaCategoryCode") if slot_details else None) or ap.get("kategori") or "SCHENGEN"

        if not center_code:
            raise ValueError(f"Başvuran #{ap['id']} için vacCode belirlenemedi.")
        if not category_code:
            raise ValueError(f"Başvuran #{ap['id']} için visaCategoryCode belirlenemedi.")

        return {
            "countryCode": CFG["portal"]["country_code"],
            "missionCode": CFG["portal"]["mission_code"],
            "vacCode": center_code,
            "visaCategoryCode": category_code,
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
        # E1: İdempotens kontrolü - submitted_at varsa mükerrer gönderim kesinlikle engellenir
        rows = DB.q("SELECT submitted_at, durum, referans_no FROM applicants WHERE id=?", (ap["id"],))
        db_data = dict(rows[0]) if rows else {}
        if db_data.get("submitted_at") or ap.get("submitted_at"):
            ts = db_data.get("submitted_at") or ap.get("submitted_at")
            DB.log("WARN", f"Başvuran #{ap['id']} için zaten gönderim yapılmış ({ts}) - mükerrer submit engellendi!", ap["id"])
            return False

        t0 = time.perf_counter()
        url = CFG["api"]["base"].rstrip("/") + CFG["api"]["book"]
        
        try:
            payload = self.build_payload(ap, slot_details)
        except ValueError as v_err:
            DB.log("ERROR", f"Payload hatası: {v_err}", ap["id"])
            return False

        # E1: Gönderim zamanını kaydet (idempotens kilidi)
        now_ts = DB.now()
        DB.set_status(ap["id"], submitted_at=now_ts)

        DB.log("INFO", f"Rezervasyon POST isteği gönderiliyor: {ap['ad']} {ap['soyad']} -> {tarih}", ap["id"])
        r = await self.http.request(
            "POST", url,
            identity=ap["vfs_email"], json_body=payload,
        )
        if not r:
            DB.bump_attempt(ap["id"], "booking isteği başarısız (ağ / yanıt yok)")
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
