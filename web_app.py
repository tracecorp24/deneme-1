"""
web_app.py - VFS Vize Botu Web Kontrol Paneli ve Orkestrasyon Arayüzü
Flask tabanlı modern arayüz:
- Aşama 1: Tarayıcı & Cloudflare Turnstile Test Modu
- Canlı Bot Modu: Katman 0 (Public Sweep) + Katman 1 (Hedefli Rezervasyon)
- Excel & SQLite Çift Yönlü Senkronizasyon
- Canlı Log & Ekran Görüntüsü İzleme
- Telegram & IMAP Entegrasyon Testleri
"""
import os
import sys
from pathlib import Path
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from core.config import DATA_DIR, SCREENSHOTS_DIR
from core.excel_manager import ExcelManager
from core.test_runner import runner_instance
from bot.service import bot_service
from bot.db import DB
from bot.excel_io import sync_inputs_to_db, write_outputs
from bot.notify import Notify
from bot.otp import OtpBridge

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# Şablon dosyası mevcut değilse üret
TEMPLATE_PATH = DATA_DIR / "vfs_bulgaristan_sablon.xlsx"
if not TEMPLATE_PATH.exists():
    ExcelManager.create_template(TEMPLATE_PATH)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    """Botun canlı yürütme durumunu, adımları, telemetriyi ve logları döndürür."""
    phase1_state = runner_instance.get_state()
    live_bot_state = bot_service.get_status()
    
    # SQLite son olayları
    recent_events = [
        {"id": r["id"], "ts": r["ts"], "level": r["level"], "msg": r["mesaj"], "applicant_id": r["applicant_id"]}
        for r in DB.q("SELECT * FROM events ORDER BY id DESC LIMIT 40")
    ]

    return jsonify({
        "phase1": phase1_state,
        "live_bot": live_bot_state,
        "events": recent_events
    })


@app.route("/api/start", methods=["POST"])
def start_test():
    """1. Aşama testini (Tarayıcı + Captcha) arka planda başlatır."""
    success = runner_instance.start_test()
    if success:
        return jsonify({"success": True, "message": "1. Aşama Testi başarıyla başlatıldı."})
    return jsonify({"success": False, "message": "Test zaten çalışıyor."}), 400


@app.route("/api/stop", methods=["POST"])
def stop_test():
    """Çalışan 1. Aşama testini durdurur."""
    runner_instance.stop_test()
    return jsonify({"success": True, "message": "1. Aşama testine durdurma sinyali gönderildi."})


@app.route("/api/start-bot", methods=["POST"])
def start_live_bot():
    """7/24 Kesintisiz Canlı Randevu Avcısını (Katman 0 + Katman 1) başlatır."""
    success = bot_service.start()
    if success:
        runner_instance.add_log("SUCCESS", "🚀 [CANLI BOT] Katman 0 Public Sweep & Katman 1 Rezervasyon Motoru Başlatıldı.")
        return jsonify({"success": True, "message": "Canlı Bot başarıyla başlatıldı."})
    return jsonify({"success": False, "message": "Canlı Bot zaten çalışıyor."}), 400


@app.route("/api/stop-bot", methods=["POST"])
def stop_live_bot():
    """Çalışan canlı botu durdurur."""
    success = bot_service.stop()
    if success:
        runner_instance.add_log("WARNING", "⏹ [CANLI BOT] Bot durdurma sinyali iletildi.")
        return jsonify({"success": True, "message": "Canlı Bot durduruldu."})
    return jsonify({"success": False, "message": "Canlı Bot zaten durmuş durumda."}), 400


@app.route("/api/template")
def download_template():
    """Örnek Excel şablonunu indirtir."""
    if not TEMPLATE_PATH.exists():
        ExcelManager.create_template(TEMPLATE_PATH)
    return send_file(
        TEMPLATE_PATH,
        as_attachment=True,
        download_name="vfs_bulgaristan_sablon.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/api/applicants", methods=["GET"])
def get_applicants():
    """SQLite ve Excel ile senkronize başvuran listesini döndürür."""
    try:
        # Önce SQLite'taki güncel başvuranları oku
        rows = DB.applicants()
        if rows:
            applicants = [dict(r) for r in rows]
            return jsonify({"count": len(applicants), "applicants": applicants, "source": "database"})
        
        # Henüz DB'de veri yoksa Excel'den parse et
        excel_path = ExcelManager.get_default_excel_path()
        if not excel_path.exists():
            applicants = ExcelManager.parse_excel(TEMPLATE_PATH)
        else:
            applicants = ExcelManager.parse_excel(excel_path)
            sync_inputs_to_db()
        return jsonify({"count": len(applicants), "applicants": applicants, "source": "excel"})
    except Exception as e:
        return jsonify({"count": 0, "applicants": [], "error": str(e)})


@app.route("/api/upload-excel", methods=["POST"])
def upload_excel():
    """Kullanıcının yüklediği Excel dosyasını kaydeder ve doğrudan SQLite'a yazar."""
    if "file" not in request.files:
        return jsonify({"success": False, "message": "Dosya bulunamadı."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "Dosya seçilmedi."}), 400

    if not file.filename.endswith((".xlsx", ".xls")):
        return jsonify({"success": False, "message": "Yalnızca Excel (.xlsx) dosyaları kabul edilir."}), 400

    dest_path = ExcelManager.get_default_excel_path()
    file.save(dest_path)

    try:
        # Veritabanına aktar
        count = sync_inputs_to_db()
        write_outputs()
        rows = DB.applicants()
        applicants = [dict(r) for r in rows]
        
        msg = f"Excel başarıyla yüklendi: {count} başvuran veritabanına aktarıldı."
        runner_instance.add_log("SUCCESS", msg)
        DB.log("INFO", msg)
        return jsonify({
            "success": True,
            "message": msg,
            "count": len(applicants),
            "applicants": applicants
        })
    except Exception as e:
        err_msg = f"Excel işlenirken hata: {str(e)}"
        runner_instance.add_log("ERROR", err_msg)
        return jsonify({"success": False, "message": err_msg}), 500


@app.route("/api/sync-excel", methods=["POST"])
def sync_excel_now():
    """Excel ile SQLite arasındaki verileri anında eşitler."""
    try:
        n = sync_inputs_to_db()
        write_outputs()
        msg = f"Excel & SQLite senkronizasyonu tamamlandı ({n} başvuran güncellendi)."
        runner_instance.add_log("INFO", msg)
        return jsonify({"success": True, "message": msg, "count": n})
    except Exception as e:
        return jsonify({"success": False, "message": f"Eşitleme hatası: {e}"}), 500


@app.route("/api/slots")
def get_slots():
    """SQLite'ta kayıtlı görülen tüm randevu slotlarını döndürür."""
    try:
        rows = DB.q("SELECT * FROM slots_seen ORDER BY ilk_gorulme DESC LIMIT 50")
        slots = [dict(r) for r in rows]
        return jsonify({"count": len(slots), "slots": slots})
    except Exception as e:
        return jsonify({"count": 0, "slots": [], "error": str(e)})


@app.route("/api/sweep-now", methods=["POST"])
def sweep_now():
    """Katman 0 Public Sweep (Login'siz genel slot taraması) işlemini anlık tetikler."""
    runner_instance.add_log("INFO", "[Katman 0] Hızlı Public Slot Taraması (login'siz) başlatılıyor...")
    res = bot_service.sweep_now()
    if res.get("success"):
        hits = res.get("hits", 0)
        runner_instance.add_log("SUCCESS" if hits > 0 else "INFO", f"[Katman 0] Public Sweep tamamlandı: {hits} yeni slot tespit edildi.")
        return jsonify(res)
    else:
        err_msg = f"Public Sweep hatası: {res.get('message')}"
        runner_instance.add_log("ERROR", f"[Katman 0] {err_msg}")
        return jsonify(res), 500


@app.route("/api/book-now", methods=["POST"])
def book_now():
    """Belirli bir başvuran için Katman 1 rezervasyon işlemini başlatır."""
    data = request.json or {}
    applicant_id = data.get("applicant_id")
    slot_date = data.get("slot_date", "")

    if not applicant_id:
        return jsonify({"success": False, "message": "Başvuran ID'si gereklidir."}), 400

    runner_instance.add_log("INFO", f"[Katman 1] Başvuran #{applicant_id} için rezervasyon süreci tetiklendi (Tarih: {slot_date})...")
    res = bot_service.book_applicant(int(applicant_id), slot_date)
    if res.get("success"):
        runner_instance.add_log("SUCCESS", f"[Katman 1] {res.get('message')}")
        return jsonify(res)
    else:
        runner_instance.add_log("WARNING", f"[Katman 1] Rezervasyon tamamlanamadı: {res.get('message')}")
        return jsonify(res), 400


@app.route("/api/test-telegram", methods=["POST"])
def test_telegram():
    """Telegram bildirim ayarlarını anında test eder."""
    import asyncio
    data = request.json or {}
    token = data.get("token", "").strip()
    chat_id = data.get("chat_id", "").strip()

    if not token or not chat_id:
        from bot.config import CFG
        token = token or CFG["telegram"].get("token", "")
        chat_id = chat_id or CFG["telegram"].get("chat_id", "")

    loop = asyncio.new_event_loop()
    try:
        ok, msg = loop.run_until_complete(Notify.test_connection(token, chat_id))
        return jsonify({"success": ok, "message": msg})
    finally:
        loop.close()


def handle_telegram_callback(cb_data: str) -> dict:
    """G1: Telegram inline buton callback data işleyici (book:{id}, skip:{id})."""
    if not cb_data:
        return {"success": False, "message": "Boş callback verisi."}
    if cb_data.startswith("book:"):
        try:
            applicant_id = int(cb_data.split(":", 1)[1])
            ap_row = DB.q("SELECT randevu_tarihi FROM applicants WHERE id=?", (applicant_id,))
            target_date = ap_row[0]["randevu_tarihi"] if ap_row and ap_row[0]["randevu_tarihi"] else ""
            res = bot_service.book_applicant(applicant_id, target_date)
            DB.log("INFO", f"Telegram callback book:{applicant_id} sonucu: {res.get('message')}", applicant_id)
            return res
        except Exception as e:
            return {"success": False, "message": f"Rezervasyon tetikleme hatası: {e}"}
    elif cb_data.startswith("skip:"):
        try:
            applicant_id = int(cb_data.split(":", 1)[1])
            DB.log("INFO", f"Telegram üzerinden slot yoksayıldı: #{applicant_id}", applicant_id)
            return {"success": True, "message": f"Başvuran #{applicant_id} için slot atlandı."}
        except Exception as e:
            return {"success": False, "message": f"Yoksayma hatası: {e}"}
    return {"success": False, "message": f"Bilinmeyen callback verisi: {cb_data}"}


@app.route("/telegram/webhook", methods=["POST"])
@app.route("/api/telegram-webhook", methods=["POST"])
def telegram_webhook():
    """G1: Telegram inline buton (book:id, skip:id) callback query webhook endpoint'i."""
    data = request.json or {}
    callback_query = data.get("callback_query")
    if not callback_query:
        return jsonify({"ok": True})

    query_id = callback_query.get("id")
    cb_data = callback_query.get("data", "")

    if query_id:
        from bot.config import CFG
        token = CFG["telegram"].get("token")
        if token:
            import urllib.request
            import json as _json
            url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
            req = urllib.request.Request(
                url,
                data=_json.dumps({"callback_query_id": query_id, "text": "İstek alındı, işleniyor..."}).encode(),
                headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(req, timeout=3)
            except Exception:
                pass

    res = handle_telegram_callback(cb_data)
    return jsonify({"ok": True, "result": res})


@app.route("/api/test-imap", methods=["POST"])
def test_imap():
    """IMAP e-posta bağlantısını ve OTP erişimini test eder."""
    data = request.json or {}
    user = data.get("user", "").strip()
    password = data.get("password", "").strip()
    host = data.get("host", "imap.gmail.com").strip()
    port = int(data.get("port", 993))

    ok, msg = OtpBridge.test_connection(host, user, password, port)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/settings", methods=["GET", "POST"])
def manage_settings():
    """Telegram, proxy ve rezervasyon yapılandırmalarını görüntüler veya günceller."""
    import yaml
    from bot.config import CONFIG_PATH, CFG

    if request.method == "POST":
        data = request.json or {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}

            if "telegram_token" in data:
                cfg.setdefault("telegram", {})["token"] = data["telegram_token"].strip()
            if "telegram_chat_id" in data:
                cfg.setdefault("telegram", {})["chat_id"] = data["telegram_chat_id"].strip()
            if "proxy_list" in data:
                proxies = [p.strip() for p in data["proxy_list"].splitlines() if p.strip()]
                cfg.setdefault("proxy", {})["isp_pool"] = proxies
            if "auto_book" in data:
                cfg.setdefault("booking", {})["auto_book"] = bool(data["auto_book"])

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True)

            runner_instance.add_log("SUCCESS", "Sistem yapılandırma ayarları başarıyla kaydedildi.")
            return jsonify({"success": True, "message": "Ayarlar başarıyla kaydedildi."})
        except Exception as e:
            return jsonify({"success": False, "message": f"Ayarlar kaydedilemedi: {e}"}), 500

    return jsonify({
        "telegram_token": CFG["telegram"].get("token", ""),
        "telegram_chat_id": CFG["telegram"].get("chat_id", ""),
        "proxies": CFG["proxy"].get("isp_pool", []),
        "auto_book": CFG.path("booking.auto_book", False)
    })


@app.route("/api/screenshot/<filename>")
def get_screenshot(filename):
    """Ekran görüntülerini servis eder."""
    safe_name = secure_filename(filename)
    return send_from_directory(SCREENSHOTS_DIR, safe_name)


if __name__ == "__main__":
    print("\n" + "=" * 65)
    print(" VFS GLOBAL BULGARİSTAN VİZE BOTU — KONTROL PANELİ")
    print(" Canlı Yönetim Adresi: http://localhost:5000")
    print("=" * 65 + "\n")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
