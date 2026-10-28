"""
core/captcha.py - Cloudflare Turnstile ve Challenge İnsansı Çözücü
Otomatik / Etkileşimli (Interactive) Turnstile doğrulamasını insan fare hareketleri
ve zamanlamasıyla çözer; onay token'ını (cf-turnstile-response) doğrular.
"""
import time
import random
import logging
from typing import Tuple, Optional
from patchright.sync_api import Page, Frame

from config import CAPTCHA_CONFIG
from core.human import HumanTiming, HumanMouse

logger = logging.getLogger("VFS_Bot.Captcha")


class TurnstileSolver:
    """Cloudflare Turnstile doğrulamasını izleyen ve çözen bileşen."""

    @staticmethod
    def get_token(page: Page) -> Optional[str]:
        """DOM içindeki gizli cf-turnstile-response input alanındaki token değerini okur."""
        try:
            token = page.evaluate("""() => {
                const el = document.querySelector('[name=\"cf-turnstile-response\"]');
                return el && el.value && el.value.length > 20 ? el.value : null;
            }""")
            return token
        except Exception:
            return None

    @classmethod
    def solve(cls, page: Page, max_wait_sec: Optional[int] = None) -> Tuple[bool, Optional[str]]:
        """
        Turnstile sürecini izler ve gerekirse insan fare hareketiyle onay kutusunu tıklar.
        
        Dönüş Değeri:
            (başarı: bool, token: Optional[str])
        """
        timeout = max_wait_sec if max_wait_sec is not None else CAPTCHA_CONFIG["turnstile_max_wait_seconds"]
        logger.info("Cloudflare Turnstile durumu izleniyor (Maksimum bekleme: %d sn)...", timeout)

        start_time = time.time()
        clicked_already = False

        while time.time() - start_time < timeout:
            # 1. Token hazır mı kontrol et (Görünmez/Otomatik mod)
            token = cls.get_token(page)
            if token:
                logger.info(">>> Cloudflare Turnstile BAŞARIYLA GEÇİLDİ! Token: %s... <<<", token[:25])
                return (True, token)

            # 2. Checkbox iframe'ini ve öğesini tespit et
            for frame in page.frames:
                if "turnstile" in frame.url or "challenge" in frame.url:
                    try:
                        box = frame.locator("input[type='checkbox'], #challenge-stage, .ctp-checkbox-label").first
                        if box.is_visible(timeout=500) and not clicked_already:
                            logger.info("Turnstile onay kutusu tespit edildi. İnsansı yaklaşımla tıklanıyor...")
                            
                            # 1. Ana sayfadaki iframe konumuna farenin insansı kavisle yaklaşması
                            iframe_el = page.locator("iframe[src*='turnstile'], iframe[src*='challenge']").first
                            if iframe_el.is_visible(timeout=500):
                                ibox = iframe_el.bounding_box()
                                if ibox:
                                    target_x = ibox["x"] + random.uniform(28.0, 42.0)
                                    target_y = ibox["y"] + ibox["height"] * random.uniform(0.42, 0.58)
                                    HumanMouse.move(page, target_x, target_y)
                                    HumanTiming.reaction_time()

                            # 2. Frame locator ile güvenilir tıklama
                            box.click()
                            clicked_already = True
                            logger.info("Turnstile onay kutusu başarıyla tıklandı.")

                            # 3. Tıklamadan sonra fareyi hafifçe kenara çekme
                            if iframe_el.is_visible(timeout=200):
                                ibox = iframe_el.bounding_box()
                                if ibox:
                                    HumanMouse.move(page, ibox["x"] + random.randint(80, 150), ibox["y"] + random.randint(30, 70))
                            
                            HumanTiming.sleep_jitter(1.5)
                            break
                    except Exception as ex:
                        logger.debug("Turnstile iframe tıklama istisnası: %s", ex)

            # Bir sonraki kontrole kadar kısa insan beklemesi
            time.sleep(CAPTCHA_CONFIG["poll_interval_seconds"])

        # Süre aşımı
        final_token = cls.get_token(page)
        if final_token:
            logger.info("Turnstile süre sonuna doğru başarıyla tamamlandı.")
            return (True, final_token)

        logger.warning("Turnstile doğrulama süresi aşıldı (%d sn). Token alınamadı.", timeout)
        return (False, None)
