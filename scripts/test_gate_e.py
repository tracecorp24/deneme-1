import asyncio
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.booker import Booker, LoginWorker, is_jwt_valid
from bot.db import DB


def make_test_jwt(exp_timestamp: float) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "user@test.com", "exp": exp_timestamp}).encode()).decode().rstrip("=")
    sig = "fake_signature_abc123"
    return f"{header}.{payload}.{sig}"


async def test_gate_e():
    print("=== Gate E Test Başlatılıyor ===")

    # 1. JWT Exp Testi
    now = time.time()
    valid_jwt = make_test_jwt(now + 3600)  # 1 saat geçerli
    expired_jwt = make_test_jwt(now - 3600) # 1 saat önce dolmuş

    assert is_jwt_valid(valid_jwt) is True, "Geçerli JWT reddedildi!"
    assert is_jwt_valid(expired_jwt) is False, "Süresi geçmiş JWT geçerli sayıldı!"
    print("[1] is_jwt_valid testi BAŞARILI.")

    # 2. Süresi geçmiş JWT ile ensure_session testi
    test_email = "jwt_test_user@example.com"
    DB.x("DELETE FROM meta WHERE k LIKE 'cooldown:%'")
    DB.session_save(test_email, authorize=expired_jwt)
    
    login_attempted = []
    class MockVfsLogin:
        async def login_start(self, account_id, password):
            login_attempted.append(account_id)
            return {"code": 400, "error": "test_stop"} # durması için

    lw = LoginWorker(None, MockVfsLogin(), None)
    test_ap = {
        "id": 888, "vfs_email": test_email, "vfs_sifre": "pass",
        "imap_app_sifre": "app_pass", "imap_sunucu": "imap.test.com"
    }
    
    # ensure_session süresi geçmiş JWT'yi fark edip login yoluna girmeli
    await lw.ensure_session(test_ap)
    assert test_email in login_attempted, f"Süresi geçmiş JWT ile login denenmedi! attempted: {login_attempted}"
    print("[2] Süresi geçmiş JWT ile ensure_session login'e girdi -> BAŞARILI.")

    # 3. Aynı başvurana iki kez book() -> ikincisi submit etmiyor (İdempotens)
    submit_calls = []
    class MockHttpBooking:
        async def request(self, method, url, **kwargs):
            submit_calls.append(kwargs.get("json_body"))
            class MockResp:
                status_code = 200
                def json(self):
                    return {"referenceNumber": "REF-TEST-9999"}
            return MockResp()

    class MockNotify:
        async def send(self, *args, **kwargs):
            pass

    booker = Booker(MockHttpBooking(), None, MockNotify())

    # Başvuran 889 ekle
    DB.x("DELETE FROM applicants WHERE id=889")
    DB.upsert_applicant({
        "id": 889, "ad": "Can", "soyad": "Test", "vfs_email": "can889@test.com",
        "pasaport_no": "P1234567", "dogum_tarihi": "1995-01-01", "merkez_tercih": "IST",
        "kategori": "SCHENGEN", "durum": "PENDING"
    })
    ap_data = dict(DB.q("SELECT * FROM applicants WHERE id=889")[0])

    # 1. Çağrı: Gönderilmeli
    res1 = await booker.book(ap_data, "2026-11-20")
    assert res1 is True, "İlk rezervasyon başarısız oldu!"
    assert len(submit_calls) == 1, f"Beklenen 1 submit çağrısı, gelen: {len(submit_calls)}"

    # 2. Çağrı: İdempotens devreye girmeli, submit etmemeli
    res2 = await booker.book(ap_data, "2026-11-20")
    assert res2 is False, "İkinci rezervasyon engellenmedi!"
    assert len(submit_calls) == 1, f"İkinci çağrıda tekrar submit edildi! Toplam submit: {len(submit_calls)}"
    print("[3] İkinci book() çağrısı submitted_at kontrolüyle engellendi -> BAŞARILI.")

    # Temizlik
    DB.x("DELETE FROM applicants WHERE id=889")
    DB.session_clear(test_email)

    print("\nGate E BASARIYLA GECILDI!")


if __name__ == "__main__":
    asyncio.run(test_gate_e())
