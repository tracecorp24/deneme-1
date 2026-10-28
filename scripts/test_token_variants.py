"""
scripts/test_token_variants.py - Token Başlığı Varyant Testi (a/b/c/d)
VFS Lift API endpoint'ine:
 (a) Token'sız
 (b) x-auth-token ile
 (c) authorization: Bearer ... ile
 (d) Hem x-auth-token hem authorization ile
istek atar ve yanıtları karşılaştırır.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import CFG
from bot.db import DB
from bot.http import VfsHttp
from bot.proxy import ProxyManager

URL = CFG["api"]["base"].rstrip("/") + CFG["api"]["public_earliest"]
BODY = {
    "missionCode": CFG["portal"]["mission_code"],
    "countryCode": CFG["portal"]["country_code"],
    "cultureCode": CFG["portal"]["culture_code"],
}


async def test_variants():
    print("=" * 65)
    print(" VFS LIFT API TOKEN BAŞLIĞI VARYANT TESTİ")
    print(f" Endpoint: {URL}")
    print("=" * 65)

    raw_token = (CFG["portal"].get("x_auth_token") or "").strip()
    bearer_token = raw_token if raw_token.lower().startswith("bearer ") else f"Bearer {raw_token}"
    clean_token = raw_token[7:].strip() if raw_token.lower().startswith("bearer ") else raw_token

    print(f"Ham Token: {raw_token[:30]}...")
    print(f"Bearer Token: {bearer_token[:30]}...")
    print(f"Clean Token: {clean_token[:30]}...\n")

    variants = [
        ("Varyant A: Token'sız (Boş)", {}),
        ("Varyant B: Sadece x-auth-token (Clean)", {"x-auth-token": clean_token}),
        ("Varyant B2: Sadece x-auth-token (Bearer)", {"x-auth-token": bearer_token}),
        ("Varyant C: Sadece authorization (Bearer)", {"authorization": bearer_token}),
        ("Varyant D: Hem authorization hem x-auth-token", {
            "authorization": bearer_token,
            "x-auth-token": clean_token
        }),
    ]

    proxy_mgr = ProxyManager()
    http = VfsHttp(proxy_mgr)

    results = []
    try:
        # Önce cf_clearance hazır olduğundan emin ol
        print("[*] cf_clearance doğrulanıyor...")
        ok = await http.ensure_cf_clearance("public", proxy_mgr.healthy("public"))
        print(f"    cf_clearance durumu: {'OK' if ok else 'YOK'}\n")

        for i, (name, headers) in enumerate(variants):
            print(f"--- İstek Gönderiliyor: {name} ---")
            print(f"    Ek Başlıklar: {list(headers.keys())}")
            
            # request metoduna doğrudan headers parametresi ver
            # (retries=1 veriyoruz ki gereksiz beklemesin)
            resp = await http.request(
                "POST",
                URL,
                identity="public",
                json_body=BODY,
                headers=headers,
                retries=1,
            )

            status = resp.status_code if resp else "None"
            text_snippet = (resp.text[:250].replace("\n", " ").replace("\r", "")) if resp else "Hata"
            if resp:
                print(f"    -> Status: {status}")
                print(f"    -> Body: {text_snippet}")
                results.append((name, status, text_snippet))
            else:
                print("    -> Yanıt Alınamadı (None)")
                results.append((name, "None", "Hata"))
            print()

            if i < len(variants) - 1:
                # Son yanıtın durumuna göre bekle: 429 veya hız sınırı varsa 60s, normalse 15s
                is_rate_limited = (status == 429 or "429202" in text_snippet)
                wait_sec = 60 if is_rate_limited else 15
                print(f"    [*] Sonraki varyant öncesi {wait_sec}s bekleniyor ({'429 hız sınırı' if is_rate_limited else 'güvenli aralık'})...\n")
                await asyncio.sleep(wait_sec)

    finally:
        await http.close()

    print("=" * 65)
    print(" VARYANT TESTİ KARŞILAŞTIRMA TABLOSU")
    print("=" * 65)
    for name, status, body in results:
        print(f"• {name.ljust(45)}: HTTP {status} | {body[:60]}")


if __name__ == "__main__":
    asyncio.run(test_variants())
