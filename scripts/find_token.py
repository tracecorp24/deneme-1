"""
scripts/find_token.py - VFS Global lift-api x-auth-token Keşif Aracı
Sayfayı açar, ağ isteklerini, başlıkları ve localStorage'ı dinler;
Bulunan token'ı token.txt ve .env dosyasına yazar.
"""
from __future__ import annotations
import asyncio
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patchright.async_api import async_playwright
from bot.config import CFG
from bot.db import DB

TARGET_URL = CFG["portal"]["base"] + "/book-an-appointment"


async def find_token():
    print("=" * 60)
    print(" VFS GLOBAL X-AUTH-TOKEN KEŞİF ARACI BAŞLATILIYOR")
    print(f" Hedef URL: {TARGET_URL}")
    print("=" * 60)

    token_found: list[str] = []
    user_data_dir = str(ROOT / "data" / "chrome_profile")
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    headless = CFG["http"].get("headless", False)

    async with async_playwright() as p:
        print("[1] Chrome tarayıcısı başlatılıyor...")
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel="chrome",
            headless=headless,
            no_viewport=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars"
            ]
        )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        async def inspect_request(req):
            if "lift-api" in req.url or "appointment" in req.url or "vfs" in req.url:
                headers = await req.all_headers()
                for h_name, h_val in headers.items():
                    if h_name.lower() in ("x-auth-token", "x-authtoken", "authorization"):
                        if h_val and h_val not in token_found:
                            print(f"\n[!] İstek Başlığında Token Yakalandı ({h_name}): {h_val[:30]}...")
                            token_found.append(h_val)

        page.on("request", inspect_request)

        print("[2] Randevu tanıtım sayfası açılıyor...")
        try:
            await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(3)

            # Çerez izin butonu varsa tıkla
            try:
                accept_btn = page.locator("#onetrust-accept-btn-handler")
                if await accept_btn.is_visible(timeout=3000):
                    await accept_btn.click()
                    print("    Çerez onayı verildi.")
            except Exception:
                pass

            # 'Book now' butonunu bul ve tıkla
            print("[3] 'Book now' butonu aranıyor...")
            book_now = page.locator("a:has-text('Book now'), button:has-text('Book now')").first
            if await book_now.is_visible(timeout=5000):
                print("    'Book now' tıklanıyor, yeni sekme bekleniyor...")
                async with ctx.expect_page() as page_info:
                    await book_now.click()
                login_page = await page_info.value
                await login_page.wait_for_load_state("domcontentloaded")
                login_page.on("request", inspect_request)
                print(f"    Yeni sayfa açıldı: {login_page.url}")
                page = login_page

            # 10 saniye boyunca istekleri ve localStorage'ı dinle
            print("[4] Ağ ve Storage dinleniyor (10 saniye)...")
            for _ in range(10):
                if token_found:
                    break

                # localStorage kontrolü
                try:
                    storage_token = await page.evaluate("""() => {
                        for (let i = 0; i < localStorage.length; i++) {
                            const k = localStorage.key(i);
                            if (k && (k.toLowerCase().includes('token') || k.toLowerCase().includes('auth'))) {
                                const val = localStorage.getItem(k);
                                if (val && val.length > 20) return val;
                            }
                        }
                        return null;
                    }""")
                    if storage_token and storage_token not in token_found:
                        print(f"\n[!] localStorage içinde Token Bulundu: {storage_token[:30]}...")
                        token_found.append(storage_token)
                        break
                except Exception:
                    pass

                await asyncio.sleep(1)

        finally:
            await ctx.close()

    # Sonuçları değerlendir ve kaydet
    token = token_found[0] if token_found else None
    token_file = ROOT / "token.txt"
    env_file = ROOT / ".env"

    if token:
        print(f"\n[BAŞARILI] Token elde edildi: {token[:35]}...")
        # 1. token.txt'ye yaz
        token_file.write_text(token.strip(), encoding="utf-8")
        print(f"    -> {token_file.name} dosyasına yazıldı.")

        # 2. .env dosyasına yaz/güncelle
        update_env_token(env_file, token.strip())
        print(f"    -> {env_file.name} (VFS_X_TOKEN) güncellendi.")

        # 3. SQLite DB meta tablosuna zaman damgasıyla kaydet
        DB.meta_set("x_auth_token", token.strip())
        DB.meta_set("x_token_ts", str(time.time()))
        print("    -> SQLite meta (x_token_ts) kaydedildi.")
        return token
    else:
        print("\n[BİLGİ] SPA ilk açılışta doğrudan x-auth-token göndermedi.")
        print("        Public endpoint kontrol ediliyor...")
        return None


def update_env_token(env_path: Path, token: str):
    """Token'ı .env dosyasına ekler veya mevcut VFS_X_TOKEN satırını günceller."""
    lines = []
    found = False
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VFS_X_TOKEN="):
                    lines.append(f"VFS_X_TOKEN={token}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"VFS_X_TOKEN={token}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    asyncio.run(find_token())
