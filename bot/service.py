"""
bot/service.py - Arka Plan Bot Servisi ve Süreç Yöneticisi
Katman 0 (Public Sweep) ve Katman 1 (Rezervasyon) döngülerini yönetir,
Web Kontrol Paneli ve API ile çift yönlü köprü kurar.
"""
from __future__ import annotations
import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .config import CFG
from .db import DB
from .excel_io import sync_inputs_to_db, write_outputs
from .http import VfsHttp
from .notify import Notify
from .otp import OtpBridge
from .poller import PublicPoller
from .proxy import ProxyManager
from .vfs import VfsClient
from .booker import Booker, LoginWorker

logger = logging.getLogger("VFS_Bot.Service")


class BotService:
    """7/24 Kesintisiz VFS Bot Çalıştırıcısı ve Servis Yöneticisi."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self.is_running = False
        self.start_time: Optional[float] = None
        
        # Bot bileşenleri
        self.proxy_mgr: Optional[ProxyManager] = None
        self.http: Optional[VfsHttp] = None
        self.vfs: Optional[VfsClient] = None
        self.notify: Optional[Notify] = None
        self.booker: Optional[Booker] = None
        self.login_worker: Optional[LoginWorker] = None
        self.poller: Optional[PublicPoller] = None

    def start(self) -> bool:
        """Canlı bot arka plan görevlerini başlatır."""
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.start_time = time.time()

        self._thread = threading.Thread(target=self._run_loop, name="VFS_LiveBot", daemon=True)
        self._thread.start()
        DB.log("INFO", "Canlı Bot Servisi başlatıldı (Katman 0 + Katman 1)")
        return True

    def stop(self) -> bool:
        """Canlı botu güvenli bir şekilde durdurur."""
        with self._lock:
            if not self.is_running:
                return False
            self.is_running = False

        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

        DB.log("INFO", "Canlı Bot Servisi durdurma talebi iletildi.")
        return True

    def _run_loop(self):
        """Arka plan thread'inde asyncio döngüsünü çalıştırır."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        # Bileşenleri başlat
        self.proxy_mgr = ProxyManager()
        self.http = VfsHttp(self.proxy_mgr)
        self.vfs = VfsClient(self.http)
        self.notify = Notify()
        self.login_worker = LoginWorker(self.http, self.vfs, self.notify)
        self.booker = Booker(self.http, self.vfs, self.notify)
        self.poller = PublicPoller(self.http, self.vfs, self.notify, self.booker, self.login_worker)

        async def _main_task():
            # Başlangıç bildirimi
            await self.notify.send(
                "🚀 <b>VFS Bulgaristan Vize Botu Çalışıyor</b>\n"
                "• Katman 0: Public Sweep (Sıfır Riskli Genel Yoklama)\n"
                "• Katman 1: Hedefli IMAP & Otomatik Rezervasyon Hazır"
            )

            # Excel'i DB ile ilk eşitleme
            try:
                sync_inputs_to_db()
                write_outputs()
            except Exception as e:
                DB.log("WARN", f"İlk Excel senkronizasyonu istisnası: {e}")

            # Eşzamanlı görevler
            from .excel_io import excel_sync_loop
            tasks = [
                asyncio.create_task(self.poller.run()),
                asyncio.create_task(excel_sync_loop()),
                asyncio.create_task(self.notify.heartbeat_loop())
            ]

            # Durdurma sinyalini bekle
            await self._stop_event.wait()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self.http.close()

        try:
            self._loop.run_until_complete(_main_task())
        except Exception as exc:
            logger.error("Bot loop hatası: %s", exc)
            DB.log("ERROR", f"Bot ana döngü hatası: {exc}")
        finally:
            with self._lock:
                self.is_running = False
            self._loop.close()
            DB.log("INFO", "Canlı Bot Servisi tamamen durduruldu.")

    def sweep_now(self) -> Dict[str, Any]:
        """Anlık olarak tek seferlik Katman 0 Public Sweep çalıştırır."""
        try:
            if self.is_running and self._loop and self._loop.is_running() and self.poller:
                # F1: Çalışan botun event loop'una run_coroutine_threadsafe ile bağlan
                future = asyncio.run_coroutine_threadsafe(self.poller.sweep_once(), self._loop)
                hits = future.result(timeout=60)
                return {"success": True, "hits": hits, "message": f"{hits} yeni bildirim üretildi."}
            else:
                # Bot kapalıysa tek seferlik loop kur
                async def _do():
                    proxy_mgr = ProxyManager()
                    http = VfsHttp(proxy_mgr)
                    try:
                        vfs = VfsClient(http)
                        notify = Notify()
                        poller = PublicPoller(http, vfs, notify)
                        return await poller.sweep_once()
                    finally:
                        await http.close()

                loop = asyncio.new_event_loop()
                try:
                    hits = loop.run_until_complete(_do())
                    return {"success": True, "hits": hits, "message": f"{hits} yeni bildirim üretildi."}
                finally:
                    loop.close()
        except Exception as e:
            return {"success": False, "hits": 0, "message": str(e)}

    def book_applicant(self, applicant_id: int, tarih: str) -> Dict[str, Any]:
        """Belirli bir başvuran için Katman 1 rezervasyon sürecini manuel tetikler."""
        rows = DB.q("SELECT * FROM applicants WHERE id=?", (applicant_id,))
        if not rows:
            return {"success": False, "message": f"Başvuran #{applicant_id} bulunamadı."}
        ap = dict(rows[0])

        # F2: Hesap kilidi kontrolü (eşzamanlı rezervasyon koruması)
        if not DB.acquire_booking_lock(applicant_id, owner="manual_panel"):
            DB.log("WARN", f"Manuel rezervasyon engellendi (hesap kilitli): #{applicant_id}", applicant_id)
            return {"success": False, "message": f"Başvuran #{applicant_id} için şu anda bir rezervasyon işlemi devam ediyor (kilitli)."}

        async def _do_book(lw: LoginWorker, bkr: Booker):
            DB.log("INFO", f"Manuel rezervasyon başlatıldı: {ap['ad']} {ap['soyad']} -> {tarih}", applicant_id)
            has_session = await lw.ensure_session(ap)
            if not has_session:
                return {"success": False, "message": "VFS oturumu açılamadı (OTP veya şifre kontrol ediniz)."}
            success = await bkr.book(ap, tarih)
            if success:
                write_outputs()
                return {"success": True, "message": "Randevu başarıyla alındı!"}
            return {"success": False, "message": "Rezervasyon isteği VFS tarafından onaylanmadı."}

        try:
            if self.is_running and self._loop and self._loop.is_running() and self.login_worker and self.booker:
                # F1: Çalışan botun event loop'una run_coroutine_threadsafe ile bağlan
                future = asyncio.run_coroutine_threadsafe(
                    _do_book(self.login_worker, self.booker),
                    self._loop
                )
                return future.result(timeout=180)
            else:
                # Bot kapalıysa tek seferlik loop kur
                async def _standalone():
                    proxy_mgr = ProxyManager()
                    http = VfsHttp(proxy_mgr)
                    try:
                        vfs = VfsClient(http)
                        notify = Notify()
                        lw = LoginWorker(http, vfs, notify)
                        booker = Booker(http, vfs, notify)
                        return await _do_book(lw, booker)
                    finally:
                        await http.close()

                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(_standalone())
                finally:
                    loop.close()
        except Exception as e:
            return {"success": False, "message": f"Hata: {str(e)}"}
        finally:
            DB.release_booking_lock(applicant_id)

    def get_status(self) -> Dict[str, Any]:
        """Tüm sistemin canlı telemetri durumunu döndürür."""
        all_applicants = DB.applicants()
        pending_count = sum(1 for a in all_applicants if a["durum"] in ("PENDING", "POLLING_SLOTS", "SESSION_ACTIVE"))
        booked_count = sum(1 for a in all_applicants if a["durum"] == "BOOKED")
        slot_found_count = sum(1 for a in all_applicants if a["durum"] == "SLOT_FOUND")

        slots_rows = DB.q("SELECT COUNT(*) as cnt FROM slots_seen")
        total_slots = slots_rows[0]["cnt"] if slots_rows else 0

        recent_events = [
            {"id": r["id"], "ts": r["ts"], "level": r["level"], "msg": r["mesaj"], "applicant_id": r["applicant_id"]}
            for r in DB.q("SELECT * FROM events ORDER BY id DESC LIMIT 50")
        ]

        uptime_s = int(time.time() - self.start_time) if self.start_time and self.is_running else 0

        return {
            "is_running": self.is_running,
            "uptime_seconds": uptime_s,
            "counts": {
                "total_applicants": len(all_applicants),
                "pending": pending_count,
                "booked": booked_count,
                "slot_found": slot_found_count,
                "slots_seen": total_slots
            },
            "meta": {
                "son_sweep": DB.meta_get("son_sweep", "Henüz yapılmadı"),
                "son_slot": DB.meta_get("son_slot", "Henüz tespit edilmedi"),
                "public_last_updated": DB.meta_get("public_last_updated", "-")
            },
            "events": recent_events
        }


# Tekil servis örneği
bot_service = BotService()
