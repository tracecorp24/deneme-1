"""
bot/poller.py - Katman 0: login'siz public sweep. Slot tespitinin tamamı burada çözülür.
"""
from __future__ import annotations
import asyncio
import random
import re
import time
from datetime import datetime
from typing import Any

from .config import CFG
from .db import DB
from .http import VfsHttp
from .notify import Notify
from .vfs import VfsClient

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}


def parse_date(value: str) -> datetime | None:
    """
    D3: Windows TR / EN locale bağımsız tarih ayrıştırıcı.
    Örnekler: "12 Nov 2026", "12 November 2026", "2026-11-12", "12/11/2026", "12.11.2026"
    """
    if not value or not isinstance(value, str):
        return None
    val = value.strip().lower()

    # 1. ISO format: 2026-11-12 veya 2026/11/12
    m_iso = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", val)
    if m_iso:
        try:
            return datetime(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            pass

    # 2. Gün/Ay/Yıl: 12/11/2026 veya 12-11-2026 veya 12.11.2026
    m_dmy = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", val)
    if m_dmy:
        try:
            return datetime(int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1)))
        except ValueError:
            pass

    # 3. İsimli ay: "12 Nov 2026", "12 November 2026"
    m_named = re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})", val)
    if m_named:
        day = int(m_named.group(1))
        m_str = m_named.group(2)
        year = int(m_named.group(3))
        month = MONTHS.get(m_str) or MONTHS.get(m_str[:3])
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    # 4. Format: "Nov 12, 2026"
    m_named2 = re.match(r"^([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", val)
    if m_named2:
        m_str = m_named2.group(1)
        day = int(m_named2.group(2))
        year = int(m_named2.group(3))
        month = MONTHS.get(m_str) or MONTHS.get(m_str[:3])
        if month:
            try:
                return datetime(year, month, day)
            except ValueError:
                pass

    return None


def in_window(tarih: str, bas: str, bit: str) -> bool:
    """
    D4: Parse hatasında False döner ve WARN loglar (sessiz yanlış pozitif engeli).
    """
    d = parse_date(tarih)
    if not d:
        DB.log("WARN", f"Aday tarih ayrıştırılamadı (pencere dışı sayıldı): '{tarih}'")
        return False

    b_d = parse_date(bas)
    if not b_d and bas:
        try:
            b_d = datetime.fromisoformat(bas)
        except Exception:
            b_d = datetime.min
    b_d = b_d or datetime.min

    e_d = parse_date(bit)
    if not e_d and bit:
        try:
            e_d = datetime.fromisoformat(bit)
        except Exception:
            e_d = datetime.max
    e_d = e_d or datetime.max

    return b_d <= d <= e_d


def night_multiplier() -> float:
    nw = CFG["polling"]["night_window"]
    now = time.strftime("%H:%M")
    return float(CFG["polling"]["night_multiplier"]) if nw[0] <= now <= nw[1] else 1.0


class PublicPoller:
    """Tek cf_clearance yeter. Hesap kilidi riski sıfır, OTP yok."""

    def __init__(self, http: VfsHttp, vfs: VfsClient, notify: Notify, booker: Any = None, login_worker: Any = None):
        self.http, self.vfs, self.notify = http, vfs, notify
        self.booker = booker
        self.login_worker = login_worker

    async def sweep_once(self) -> int:
        data = await self.vfs.public_earliest()
        if data is None:
            n = int(DB.meta_get("rl_streak", "0") or 0) + 1
            DB.meta_set("rl_streak", str(n))
            if n == 3:
                await self.notify.send("⚠️ VFS 3 kez üst üste hız sınırı verdi — proxy şart.")
            return 0
        DB.meta_set("rl_streak", "0")

        rows = self.vfs.parse_public(data)
        DB.meta_set("son_sweep", DB.now())
        DB.meta_set("public_last_updated", str(data.get("lastUpdatedOn", "")))
        hits = 0

        bekleyen = DB.applicants(durum=("PENDING", "SESSION_ACTIVE", "POLLING_SLOTS", "SLOT_FOUND"))
        for row in rows:
            h = self.vfs.slot_hash(row["merkez"], row["kategori"], row["tarih"])
            # Global slot kaydı (daha önce görülmemişse slots_seen'e ekle)
            DB.slot_is_new(h, row["merkez"], row["kategori"], row["tarih"])

            for ap in bekleyen:
                tercihler = [t.strip() for t in (ap["merkez_tercih"] or "").split(",") if t.strip()]
                if tercihler and not any(t.lower() in row["merkez"].lower() for t in tercihler):
                    continue
                if not in_window(row["tarih"], ap["tarih_baslangic"] or "", ap["tarih_bitis"] or ""):
                    continue

                # D1: Başvuran bazlı dedupe kontrolü (notified tablosu)
                if DB.applicant_notified(ap["id"], h):
                    continue

                hits += 1
                DB.meta_set("son_slot", f"{row['merkez']} {row['kategori']} {row['tarih']} @ {DB.now()}")
                DB.set_status(ap["id"], "SLOT_FOUND", randevu_tarihi=row["tarih"], merkez=row["merkez"])
                DB.log("SLOT", f"AÇIK SLOT: {row['merkez']} / {row['kategori']} / {row['tarih']}", ap["id"])
                await self.notify.slot_alert(row["merkez"], row["kategori"], row["tarih"], ap["id"])

                # Otomatik rezervasyon modu açıksa Katman 1'i tetikle
                if CFG.path("booking.auto_book", False) and self.booker and self.login_worker:
                    if not DB.acquire_booking_lock(ap["id"], owner="poller_autobook"):
                        DB.log("WARN", f"Otomatik rezervasyon atlandı (hesap kilitli): #{ap['id']}", ap["id"])
                    else:
                        try:
                            DB.log("INFO", f"Otomatik rezervasyon baslatiliyor: {ap['ad']} {ap['soyad']} -> {row['tarih']}", ap["id"])
                            has_session = await self.login_worker.ensure_session(ap)
                            if has_session:
                                await self.booker.book(ap, row["tarih"])
                            else:
                                DB.log("WARN", f"Oturum acilamadigi icin rezervasyon yapilamadi: {ap['vfs_email']}", ap["id"])
                        except Exception as b_exc:
                            DB.log("ERROR", f"Rezervasyon istisnasi: {b_exc}", ap["id"])
                        finally:
                            DB.release_booking_lock(ap["id"])

        return hits

    async def run(self) -> None:
        DB.log("INFO", "Katman 0 PublicPoller başlatıldı (Login'siz genel slot taraması)")
        while True:
            try:
                hits = await self.sweep_once()
                if hits > 0:
                    DB.log("INFO", f"Public Sweep tamamlandı: {hits} yeni bildirim üretildi.")
            except Exception as exc:
                DB.log("ERROR", f"public sweep döngü hatası: {exc}")
            lo, hi = CFG["polling"]["public_interval_s"]
            wait_sec = random.uniform(lo, hi) * night_multiplier()
            await asyncio.sleep(wait_sec)
