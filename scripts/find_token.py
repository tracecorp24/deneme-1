"""
scripts/find_token.py - VFS Global lift-api x-auth-token Keşif Aracı (Sağlamlaştırılmış Sürüm)
Sayfayı açar, tüm ağ trafiğini (istek/yanıt başlıkları) ve Storage alanlarını dinler;
Bulunan token'ı anında diske (token.txt ve .env) ve SQLite'a yazar.
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

BASE_PORTAL = CFG["portal"]["base"].rstrip("/")
TARGET_URL = BASE_PORTAL + "/book-an-appointment"
LOGIN_URL = BASE_PORTAL + "/login"


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


async def find_token():
    print("=" * 65)
    print(" VFS GLOBAL X-AUTH-TOKEN SAĞLAM KEŞİF ARACI BAŞLATILIYOR")
    print(f" Hedef URL: {TARGET_URL} (Fallback: {LOGIN_URL})")
    print("=" * 65)

    token_found: list[str] = []
    user_data_dir = str(ROOT / "data" / "chrome_profile")
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    headless = CFG["http"].get("headless", False)

    def save_token(raw_tok: str, source: str = "Ağ"):
        if not raw_tok or not isinstance(raw_tok, str):
            return False
        cleaned = raw_tok.strip()
        if len(cleaned) < 15:
            return False
        if cleaned not in token_found:
            token_found.append(cleaned)
            # Anında diske ve SQLite'a yaz (çökme durumunda veri kaybı olmaz)
            token_file = ROOT / "token.txt"
            env_file = ROOT / ".env"
            token_file.write_text(cleaned, encoding="utf-8")
            update_env_token(env_file, cleaned)
            DB.meta_set("x_auth_token", cleaned)
            DB.meta_set("x_token_ts", str(time.time()))
            print(f"\n[!] Token ({source}) Yakalandı ve Anında Kaydedildi: {cleaned[:35]}...")
            return True
        return False

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

        async def inspect_request(req):
            try:
                headers = await req.all_headers()
                for h_name, h_val in headers.items():
                    if h_name.lower() in ("x-auth-token", "x-authtoken", "authorization"):
                        save_token(h_val, source=f"Header {h_name}")
            except Exception:
                pass

        async def attach_page_listeners(p_obj):
            p_obj.on("request", inspect_request)

        # Context seviyesinde açılan her yeni sayfayı dinle
        ctx.on("page", lambda p_obj: asyncio.create_task(attach_page_listeners(p_obj)))

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await attach_page_listeners(page)

        print("[2] Tanıtım sayfası açılıyor...")
        try:
            try:
                await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=40000)
            except Exception as nav_err:
                print(f"    [!] Tanıtım sayfası açılamadı ({nav_err}), doğrudan /login sayfasına gidiliyor...")
                await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=40000)

            await asyncio.sleep(2)

            # Çerez izin butonu varsa tıkla
            try:
                accept_btn = page.locator("#onetrust-accept-btn-handler")
                if await accept_btn.is_visible(timeout=3000):
                    await accept_btn.click()
                    print("    Çerez onayı verildi.")
            except Exception:
                pass

            # 'Book now' butonu aranıyor (hata vermeden güvenli tıklama)
            print("[3] 'Book now' butonu aranıyor...")
            try:
                book_now = page.locator("a:has-text('Book now'), button:has-text('Book now')").first
                if await book_now.is_visible(timeout=4000):
                    print("    'Book now' tıklanıyor...")
                    # Yeni sekme açılırsa veya aynı sayfada yönlendirilirse güvenli bekleme
                    try:
                        async with ctx.expect_page(timeout=5000) as page_info:
                            await book_now.click()
                        login_page = await page_info.value
                        await login_page.wait_for_load_state("domcontentloaded", timeout=10000)
                        await attach_page_listeners(login_page)
                        print(f"    Yeni sekme açıldı: {login_page.url}")
                    except Exception:
                        # expect_page zaman aşımına uğrarsa aynı sekmede devam et
                        print("    Yeni sekme açılmadı, mevcut sekmede devam ediliyor.")
            except Exception as btn_err:
                print(f"    'Book now' adımı atlandı ({btn_err}).")

            # Açık olan tüm sayfalarda Storage ve Ağ dinleme
            print("[4] Tüm sekmelerde Ağ ve Storage taranıyor...")
            for _ in range(12):
                if token_found:
                    break

                for open_page in ctx.pages:
                    try:
                        storage_val = await open_page.evaluate("""() => {
                            for (let storage of [localStorage, sessionStorage]) {
                                for (let i = 0; i < storage.length; i++) {
                                    const k = storage.key(i);
                                    if (k && (k.toLowerCase().includes('token') || k.toLowerCase().includes('auth'))) {
                                        const val = storage.getItem(k);
                                        if (val && val.length > 20) return val;
                                    }
                                }
                            }
                            return null;
                        }""")
                        if storage_val:
                            save_token(storage_val, source="WebStorage")
                            break
                    except Exception:
                        pass

                await asyncio.sleep(1)

        except Exception as main_err:
            print(f"[!] Tarayıcı akışında istisna: {main_err}")
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    if token_found:
        print(f"\n[BAŞARILI] Token kullanıma hazır: {token_found[0][:35]}...")
        return token_found[0]
    else:
        print("\n[UYARI] Token yakalanamadı.")
        return None


if __name__ == "__main__":
    asyncio.run(find_token())
