"""
scripts/recon.py - İlk çalıştırılacak teşhis ve keşif aracı.
cf_clearance üretir, x-auth-token toplar, endpoint'leri yoklar ve sonuçları dökümler.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import CFG
from bot.http import VfsHttp
from bot.proxy import ProxyManager

API = CFG["api"]["base"].rstrip("/")
PROBES = [
    ("POST", CFG["api"]["public_earliest"],
     {"missionCode": CFG["portal"]["mission_code"], "countryCode": CFG["portal"]["country_code"],
      "cultureCode": CFG["portal"]["culture_code"]},
     {"x-auth-token": CFG["portal"]["x_auth_token"]} if CFG["portal"]["x_auth_token"] else {}),
    ("POST", CFG["api"]["check_slot"],
     {"countryCode": CFG["portal"]["country_code"], "missionCode": CFG["portal"]["mission_code"],
      "vacCode": CFG["centres"][0]["code"], "visaCategoryCode": CFG["categories"][0]["code"],
      "roleName": "Individual", "loginUser": "", "payCode": ""}, {}),
]


async def harvest_token(proxy: str) -> str | None:
    from patchright.async_api import async_playwright
    found: list[str] = []
    kwargs = {"channel": "chrome", "headless": False, "args": ["--disable-blink-features=AutomationControlled"]}
    if proxy:
        kwargs["proxy"] = {"server": proxy}

    async with async_playwright() as p:
        browser = await p.chromium.launch(**kwargs)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        page.on("request", lambda r: found.append(r.headers.get("x-auth-token", ""))
                if "lift-api" in r.url and r.headers.get("x-auth-token") else None)
        try:
            await page.goto(CFG["portal"]["base"], wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(10)
        finally:
            await browser.close()
    return next((t for t in found if t), None)


async def main() -> None:
    print("\n==================================================")
    print("      VFS GLOBAL RECON & TEŞHİS BAŞLATILIYOR      ")
    print("==================================================\n")

    proxy = CFG["proxy"]["isp_pool"][0] if CFG["proxy"]["isp_pool"] else ""
    http = VfsHttp(ProxyManager())

    print("[1] cf_clearance uretiliyor...")
    ok = await http.ensure_cf_clearance("public", proxy)
    print(f"    cf_clearance durumu: {'[OK] BASARILI' if ok else '[FAIL] BASARISIZ'}")

    print("\n[2] x-auth-token toplanıyor...")
    token = await harvest_token(proxy)
    print(f"    x-auth-token: {token or 'bulunamadı (public token gerekebilir)'}")

    print("\n[3] Canlı Endpoint Yoklaması (Probe):")
    for method, path, body, headers in PROBES:
        r = await http.request(method, API + path, identity="public", json_body=body, headers=headers)
        status = r.status_code if r else "YOK"
        print(f"    {method} {path} -> HTTP {status}")
        if r:
            preview = r.text[:350].replace('\n', ' ')
            print(f"       Yanıt: {preview}...")

    print("\n[4] Login / OTP şeması:")
    print(json.dumps({"login": CFG["api"]["login"], "otp": CFG["api"]["validate_otp"]}, indent=2))

    await http.close()
    print("\n[OK] Recon islemi tamamlandi.\n")


if __name__ == "__main__":
    asyncio.run(main())
