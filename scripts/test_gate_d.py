import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from bot.poller import parse_date, PublicPoller
from bot.db import DB

# Test 1: parse_date check
d = parse_date('12 Nov 2026')
print(f"parse_date('12 Nov 2026') -> {repr(d)}")
assert d == datetime(2026, 11, 12), f"parse_date failed: {d}"

# Test 2: İki başvuran aynı merkez/tarihe ayarlı, sahte slot enjekte
DB.x("UPDATE applicants SET durum='BOOKED' WHERE id NOT IN (901, 902)")
DB.x("DELETE FROM applicants WHERE id IN (901, 902)")
DB.x("DELETE FROM notified WHERE applicant_id IN (901, 902)")
DB.x("DELETE FROM slots_seen WHERE hash='fake_hash_123'")

DB.upsert_applicant({
    'id': 901, 'ad': 'Ali', 'soyad': 'Test', 'vfs_email': 'ali901@test.com',
    'merkez_tercih': 'IST', 'kategori': 'Turistik',
    'tarih_baslangic': '2026-11-01', 'tarih_bitis': '2026-11-30', 'durum': 'PENDING'
})
DB.upsert_applicant({
    'id': 902, 'ad': 'Veli', 'soyad': 'Test', 'vfs_email': 'veli902@test.com',
    'merkez_tercih': 'IST', 'kategori': 'Turistik',
    'tarih_baslangic': '2026-11-01', 'tarih_bitis': '2026-11-30', 'durum': 'PENDING'
})

telegram_alerts = []
class MockNotify:
    async def slot_alert(self, merkez, kategori, tarih, applicant_id):
        telegram_alerts.append((applicant_id, merkez, tarih))

class MockVfs:
    async def public_earliest(self):
        return {'vacList': []}
    def parse_public(self, data):
        return [{'merkez': 'Istanbul', 'kategori': 'Turistik', 'tarih': '12 Nov 2026'}]
    def slot_hash(self, m, k, t):
        return 'fake_hash_123'

poller = PublicPoller(None, MockVfs(), MockNotify())
hits = asyncio.run(poller.sweep_once())

ap1 = dict(DB.q("SELECT durum, randevu_tarihi FROM applicants WHERE id=901")[0])
ap2 = dict(DB.q("SELECT durum, randevu_tarihi FROM applicants WHERE id=902")[0])

print(f"Sweep hits: {hits}")
print(f"Telegram alerts: {telegram_alerts}")
print(f"Applicant 901: {ap1}")
print(f"Applicant 902: {ap2}")

assert hits == 2, f"Expected 2 hits, got {hits}"
assert len(telegram_alerts) == 2, f"Expected 2 alerts, got {len(telegram_alerts)}"
assert ap1['durum'] == 'SLOT_FOUND', f"Applicant 901 not SLOT_FOUND: {ap1}"
assert ap2['durum'] == 'SLOT_FOUND', f"Applicant 902 not SLOT_FOUND: {ap2}"

# İkinci sweep: dedupe çalışmalı, tekrar uyarılmamalı
hits2 = asyncio.run(poller.sweep_once())
print(f"Second sweep hits (dedupe): {hits2}")
assert hits2 == 0, f"Expected 0 hits on dedupe, got {hits2}"

# Temizlik
DB.x("DELETE FROM applicants WHERE id IN (901, 902)")
DB.x("DELETE FROM notified WHERE applicant_id IN (901, 902)")
DB.x("DELETE FROM slots_seen WHERE hash='fake_hash_123'")
DB.x("UPDATE applicants SET durum='PENDING' WHERE id=1")

print("Gate D BASARIYLA GECILDI!")
