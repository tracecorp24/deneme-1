"""
bot/notify.py - Telegram: Bot API doğrudan çağrılır. Inline buton + dedupe + heartbeat.
"""
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
            f"🔔 <b>VFS RANDEVU SLOTU AÇILDI!</b>\n"
            f"📍 <b>Merkez:</b> {merkez}\n"
            f"📑 <b>Kategori:</b> {kategori}\n"
            f"📅 <b>Tarih:</b> {tarih}\n"
            f"👤 <b>Başvuran ID:</b> #{applicant_id}",
            keyboard=[[
                {"text": "⚡ Rezerve Et", "callback_data": f"book:{applicant_id}"},
                {"text": "❌ Yoksay", "callback_data": f"skip:{applicant_id}"},
            ]],
            dedupe_key=key,
        )

    async def heartbeat(self) -> None:
        aktif = len(DB.applicants(durum=("PENDING", "SESSION_ACTIVE", "POLLING_SLOTS")))
        await self.send(
            f"💓 <b>VFS Bot Ayakta</b>\n"
            f"İzlenen aktif başvuran: {aktif}\n"
            f"Son slot kaydı: {DB.meta_get('son_slot', '-')}",
            dedupe_key="heartbeat",
        )

    async def heartbeat_loop(self) -> None:
        while True:
            await self.heartbeat()
            await asyncio.sleep(float(CFG["telegram"]["heartbeat_s"]))

    async def telegram_polling_loop(self) -> None:
        """Localhost fallback: Webhook yoksa getUpdates ile inline buton callback'lerini yakalar."""
        if not self.token:
            return
        offset = 0
        DB.log("INFO", "Telegram getUpdates polling dinleyicisi başlatıldı")
        while True:
            try:
                url = f"{self.base}/getUpdates"
                params = {"offset": offset, "timeout": 20, "allowed_updates": ["callback_query"]}
                async with AsyncSession(timeout=25) as s:
                    resp = await s.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        for update in data.get("result", []):
                            offset = max(offset, update["update_id"] + 1)
                            cb = update.get("callback_query")
                            if cb:
                                await self._handle_callback_query(cb, s)
                    elif resp.status_code == 409:
                        # Webhook aktif olduğu için getUpdates 409 döner; webhook varsa polling uyur
                        await asyncio.sleep(30)
                    else:
                        await asyncio.sleep(5)
            except Exception:
                await asyncio.sleep(5)

    async def _handle_callback_query(self, cb: dict, s: AsyncSession) -> None:
        query_id = cb.get("id")
        data = cb.get("data", "")
        if query_id:
            try:
                await s.post(f"{self.base}/answerCallbackQuery", json={
                    "callback_query_id": query_id,
                    "text": "İstek alındı, işleniyor..."
                })
            except Exception:
                pass

        if data.startswith("book:"):
            try:
                applicant_id = int(data.split(":", 1)[1])
                ap_row = DB.q("SELECT randevu_tarihi FROM applicants WHERE id=?", (applicant_id,))
                target_date = ap_row[0]["randevu_tarihi"] if ap_row and ap_row[0]["randevu_tarihi"] else ""
                from bot.service import bot_service
                res = bot_service.book_applicant(applicant_id, target_date)
                msg = res.get("message", "")
                await self.send(f"⚡ <b>Rezervasyon Tetiklendi (#{applicant_id}):</b> {msg}")
                DB.log("INFO", f"Telegram getUpdates book:{applicant_id} sonucu: {msg}", applicant_id)
            except Exception as e:
                DB.log("ERROR", f"Telegram getUpdates callback book hatası: {e}")
        elif data.startswith("skip:"):
            try:
                applicant_id = int(data.split(":", 1)[1])
                await self.send(f"❌ <b>Slot Atlandı:</b> Başvuran #{applicant_id} için işlem yapılmadı.")
                DB.log("INFO", f"Telegram getUpdates skip:{applicant_id} çağrıldı.", applicant_id)
            except Exception as e:
                DB.log("ERROR", f"Telegram getUpdates callback skip hatası: {e}")

    @classmethod
    async def test_connection(cls, token: str, chat_id: str) -> tuple[bool, str]:
        """Test Telegram Bot API by sending a ping message."""
        if not token or not chat_id:
            return False, "Telegram Bot Token veya Chat ID boş olamaz."
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "✅ <b>VFS Global Bulgaristan Botu:</b> Telegram bildirim bağlantısı başarıyla kuruldu!",
            "parse_mode": "HTML"
        }
        async with AsyncSession(timeout=10) as s:
            try:
                resp = await s.post(url, json=payload)
                if resp.status_code == 200 and resp.json().get("ok"):
                    return True, "Telegram test mesajı başarıyla gönderildi!"
                return False, f"Telegram hatası (HTTP {resp.status_code}): {resp.text}"
            except Exception as e:
                return False, f"Bağlantı hatası: {str(e)}"
