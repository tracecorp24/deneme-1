import asyncio
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.db import DB
from bot.service import BotService


def test_gate_f():
    print("=== Gate F Test Başlatılıyor ===")

    # 1. DB Kilit Testi
    app_id = 950
    DB.x("DELETE FROM applicants WHERE id=?", (app_id,))
    DB.upsert_applicant({
        "id": app_id, "ad": "Eşzamanlı", "soyad": "Test", "vfs_email": "lock_test@example.com",
        "pasaport_no": "U999999", "dogum_tarihi": "1990-01-01", "merkez_tercih": "IST",
        "kategori": "SCHENGEN", "durum": "PENDING", "imap_app_sifre": "pass"
    })
    DB.release_booking_lock(app_id)

    # Doğrudan lock almayı test et
    lock1 = DB.acquire_booking_lock(app_id, "owner1")
    assert lock1 is True, "İlk kilit alınamadı!"
    lock2 = DB.acquire_booking_lock(app_id, "owner2")
    assert lock2 is False, "İkinci kilit engellenmedi!"
    DB.release_booking_lock(app_id)
    print("[1] DB acquire_booking_lock / release_booking_lock testi BAŞARILI.")

    # 2. Panelden aynı başvurana paralel iki rezervasyon testi
    service = BotService()

    # Sahte Book & Login worker ile book_applicant testi
    call_counts = {"post": 0, "locked": 0}

    class MockBooker:
        async def book(self, ap, tarih):
            call_counts["post"] += 1
            await asyncio.sleep(0.5) # İşlem devam ediyor efekti
            return True

    class MockLW:
        async def ensure_session(self, ap):
            return True

    # Çalışan bot varmış gibi ayarla
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    service.is_running = True
    service._loop = loop
    service.login_worker = MockLW()
    service.booker = MockBooker()

    results = []

    def call_book(idx):
        res = service.book_applicant(app_id, "2026-11-25")
        results.append((idx, res))

    t1 = threading.Thread(target=call_book, args=(1,))
    t2 = threading.Thread(target=call_book, args=(2,))

    t1.start()
    time.sleep(0.05) # t1'in kilidi aldığından emin olmak için minik bekleme
    t2.start()

    t1.join()
    t2.join()

    # Loop temizliği
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()

    print(f"Sonuçlar: {results}")
    print(f"Toplam POST / submit çağrısı: {call_counts['post']}")

    assert call_counts["post"] == 1, f"Beklenen 1 POST çağrısı, yapılan: {call_counts['post']}"
    
    # Biri başarıyla rezerve edilmiş olmalı, diğeri kilitli dönmüş olmalı
    messages = [r[1]["message"] for r in results]
    assert any("kilitli" in m.lower() for m in messages), f"Kilitli mesajı dönmedi! Gelen mesajlar: {messages}"
    print("[2] Paralel iki book_applicant çağrısından ikincisi kilitli döndü, tek POST gitti -> BAŞARILI.")

    # Temizlik
    DB.release_booking_lock(app_id)
    DB.x("DELETE FROM applicants WHERE id=?", (app_id,))

    print("\nGate F BASARIYLA GECILDI!")


if __name__ == "__main__":
    test_gate_f()
