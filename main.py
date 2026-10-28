"""
main.py - VFS Vize Botu (Aşama 1: İnsansı Sayfa Açma ve Captcha Çözücü)

Bu modül, botun ilk aşamasını icra eder:
1. Resmi Google Chrome + Patchright + Kalıcı Profil (Persistent Profile) ile başlar.
2. plan.md gereği ısınma akışını (warm-up) izleyerek Randevu sayfasından giriş yapar.
3. Çerez izinlerini insan gibi kabul eder.
4. 'Book now' butonuna Bézier kavisli fare hareketi ile tıklar.
5. Açılan Giriş (Login) sayfasında Cloudflare Turnstile captcha'sını izler ve insansı hareketlerle çözer.
6. Oturum çerezlerini (cf_clearance vb.) diske saklar.
"""
import sys
import logging
from config import SCREENSHOTS_DIR
from core import BrowserManager, TurnstileSolver, SessionManager, HumanTiming

# Loglama ayarları
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("VFS_Bot.Main")


def run_stage_one():
    logger.info("==================================================")
    logger.info("   VFS Vize Botu - Aşama 1: Sayfa Açma & Captcha  ")
    logger.info("==================================================")

    manager = BrowserManager(headless=False)

    try:
        # 1. Tarayıcıyı başlat
        page = manager.start()

        # 2. Isınma akışı: Randevu sayfası -> Çerez Onayı -> 'Book now' tıklaması
        logger.info("[Adım 1/4] Isınma akışı (warm-up) başlatılıyor...")
        login_page = manager.navigate_warmup_flow()

        # 3. Cloudflare Turnstile tespiti ve insansı çözümü
        logger.info("[Adım 2/4] Cloudflare Turnstile denetimi ve çözümü başlatılıyor...")
        success, token = TurnstileSolver.solve(login_page, max_wait_sec=30)

        if not success:
            logger.error("Turnstile çözülemedi veya süre aşımına uğradı!")
            screenshot_path = manager.take_screenshot(login_page, name_prefix="turnstile_failed")
            logger.info("Hata ekran görüntüsü kaydedildi: %s", screenshot_path)
            return False

        logger.info("Turnstile başarıyla geçildi! Token onaylandı.")

        # 4. Giriş formunun hazır olduğunu teyit et
        logger.info("[Adım 3/4] Giriş formu kontrol ediliyor...")
        HumanTiming.sleep_jitter(1.5)
        
        email_input = login_page.locator("input[type='email'], input[formcontrolname='username'], #mat-input-0").first
        is_ready = email_input.is_visible(timeout=5000)
        
        if is_ready:
            logger.info(">>> TEBRİKLER! Giriş formu (Email / Şifre alanları) tamamen hazır ve aktif! <<<")
        else:
            logger.warning("Giriş formu henüz tam görünür değil.")

        # 5. Çerezleri kaydet (plan.md Bölüm 6)
        logger.info("[Adım 4/4] Oturum çerezleri (cf_clearance dahil) diske kaydediliyor...")
        SessionManager.save_session(manager.context, session_id="bgr_vfs")

        # Başarı ekran görüntüsü al
        screenshot_path = manager.take_screenshot(login_page, name_prefix="stage1_success")
        logger.info("Başarı ekran görüntüsü kaydedildi: %s", screenshot_path)

        logger.info("==================================================")
        logger.info("   AŞAMA 1 BAŞARIYLA TAMAMLANDI!                  ")
        logger.info("   - Cloudflare koruması aşıldı                   ")
        logger.info("   - Turnstile 'Başarılı' onayı alındı            ")
        logger.info("   - Ban yemeyen insansı profil hazırlandı        ")
        logger.info("==================================================")
        
        HumanTiming.sleep_jitter(3.0)
        return True

    except Exception as e:
        logger.exception("Aşama 1 sırasında beklenmeyen bir hata meydana geldi: %s", e)
        if manager.current_page:
            try:
                manager.take_screenshot(manager.current_page, name_prefix="crash_error")
            except Exception:
                pass
        return False
    finally:
        manager.stop()


if __name__ == "__main__":
    success = run_stage_one()
    sys.exit(0 if success else 1)
