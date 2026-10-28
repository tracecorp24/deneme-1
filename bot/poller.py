"""
bot/poller.py - Katman 0: login'siz public sweep. Slot tespitinin tamamı burada çözülür.
"""
from __future__ import annotations
import asyncio
import random
import time
from datetime import datetime

from .config import CFG
from .db import DB
from .http import VfsHttp
from .notify import Notify
from .vfs import VfsClient

DATE_FORMATS = ["%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"]


def parse_date(value: str) -> datetime | None:
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def in_window(tarih: str, bas: str, bit: str) -> bool:
    d = parse_date(tarih)
    if not d:
        return True  # Tarih parse edilemediyse filtreleme, alarm üret
    try:
        b_d = datetime.fromisoformat(bas) if bas else datetime.min
        e_d = datetime.fromisoformat(bit) if bit else datetime.max
        return b_d <= d <= e_d
    except ValueError:
        return True


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
        rows = self.vfs.parse_public(data)
        if data:
            DB.meta_set("son_sweep", DB.now())
            DB.meta_set("public_last_updated", str(data.get("lastUpdatedOn", "")))
        hits = 0

        bekleyen = DB.applicants(durum=("PENDING", "SESSION_ACTIVE", "POLLING_SLOTS", "SLOT_FOUND"))
        for row in rows:
            for ap in bekleyen:
                tercihler = [t.strip() for t in (ap["merkez_tercih"] or "").split(",") if t.strip()]
                if tercihler and not any(t.lower() in row["merkez"].lower() for t in tercihler):
                    continue
                if not in_window(row["tarih"], ap["tarih_baslangic"] or "", ap["tarih_bitis"] or ""):
                    continue
                h = self.vfs.slot_hash(row["merkez"], row["kategori"], row["tarih"])
                if not DB.slot_is_new(h, row["merkez"], row["kategori"], row["tarih"]):
                    continue
                hits += 1
                DB.meta_set("son_slot", f"{row['merkez']} {row['kategori']} {row['tarih']} @ {DB.now()}")
                DB.set_status(ap["id"], "SLOT_FOUND", randevu_tarihi=row["tarih"], merkez=row["merkez"])
                DB.log("SLOT", f"AÇIK SLOT: {row['merkez']} / {row['kategori']} / {row['tarih']}", ap["id"])
                await self.notify.slot_alert(row["merkez"], row["kategori"], row["tarih"], ap["id"])

                # Otomatik rezervasyon modu açıksa Katman 1'i tetikle
                if CFG.path("booking.auto_book", False) and self.booker and self.login_worker:
                    DB.log("INFO", f"Otomatik rezervasyon baslatiliyor: {ap['ad']} {ap['soyad']} -> {row['tarih']}", ap["id"])
                    try:
                        has_session = await self.login_worker.ensure_session(ap)
                        if has_session:
                            await self.booker.book(ap, row["tarih"])
                        else:
                            DB.log("WARN", f"Oturum acilamadigi icin rezervasyon yapilamadi: {ap['vfs_email']}", ap["id"])
                    except Exception as b_exc:
                        DB.log("ERROR", f"Rezervasyon istisnasi: {b_exc}", ap["id"])

        return hits

    async def run(self) -> None:
        DB.log("INFO", "Katman 0 PublicPoller başlatıldı (Login'siz genel slot taraması)")
        while True:
            try:
                hits = await self.sweep_once()
                if hits > 0:
                    DB.log("INFO", f"Public Sweep tamamlandı: {hits} yeni slot tespit edildi.")
            except Exception as exc:
                DB.log("ERROR", f"public sweep döngü hatası: {exc}")
            lo, hi = CFG["polling"]["public_interval_s"]
            wait_sec = random.uniform(lo, hi) * night_multiplier()
            await asyncio.sleep(wait_sec)
