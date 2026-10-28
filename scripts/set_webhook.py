"""
scripts/set_webhook.py - Telegram Bot Webhook Yönetim Aracı
Kullanım:
  1. Webhook durumunu sorgulamak:
     python scripts/set_webhook.py
  2. Yeni webhook kaydetmek (ngrok veya alan adı ile):
     python scripts/set_webhook.py https://my-domain.com/api/telegram-webhook
  3. Webhook'u silip getUpdates (localhost) moduna dönmek:
     python scripts/set_webhook.py delete
"""
import sys
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.config import CFG

TOKEN = CFG["telegram"].get("token", "").strip()

if not TOKEN:
    print("[HATA] Telegram token bulunamadı! Lütfen .env (TELEGRAM_TOKEN) veya config.yaml dosyasını doldurun.")
    sys.exit(1)

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


def api_post(endpoint: str, data: dict = None):
    url = f"{BASE_URL}/{endpoint}"
    payload = json.dumps(data or {}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def api_get(endpoint: str):
    url = f"{BASE_URL}/{endpoint}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    if len(sys.argv) < 2:
        # Durum sorgula
        info = api_get("getWebhookInfo")
        print("\n=== Telegram Webhook Durumu ===")
        print(f"URL: {info.get('result', {}).get('url') or '(Webhook yok - getUpdates modu aktif)'}")
        print(f"Bekleyen Güncelleme: {info.get('result', {}).get('pending_update_count', 0)}")
        last_err = info.get('result', {}).get('last_error_message')
        if last_err:
            print(f"Son Hata: {last_err}")
        return

    arg = sys.argv[1].strip()

    if arg.lower() == "delete":
        res = api_post("deleteWebhook", {"drop_pending_updates": False})
        print(f"\n[OK] Webhook silindi: {res.get('description', 'Başarılı')}")
        print("Bot artık getUpdates (localhost) üzerinden çalışacaktır.")
    else:
        url = arg
        if not url.startswith("https://"):
            print("[HATA] Telegram webhook adresi mutlaka 'https://' ile başlamalıdır!")
            sys.exit(1)
        res = api_post("setWebhook", {
            "url": url,
            "allowed_updates": ["message", "callback_query"]
        })
        print(f"\n[OK] Webhook kuruldu -> {url}")
        print(f"Telegram Yanıtı: {res.get('description', 'Başarılı')}")


if __name__ == "__main__":
    main()
