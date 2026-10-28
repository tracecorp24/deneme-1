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
