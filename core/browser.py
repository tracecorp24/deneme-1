"""
core/browser.py - Gelişmiş Anti-Detect Tarayıcı Yöneticisi
Patchright + Resmi Google Chrome + Kalıcı Kullanıcı Profili (Persistent Context) + Stealth
"""
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from patchright.sync_api import sync_playwright, BrowserContext, Page, Playwright

from config import BROWSER_CONFIG, SCREENSHOTS_DIR, BASE_URL, APPOINTMENT_URL
from core.human import HumanTiming, HumanMouse, HumanScroll

logger = logging.getLogger("VFS_Bot.Browser")

class BrowserManager:
    """Anti-detect tarayıcı yaşam döngüsünü ve oturumunu yöneten sınıf."""

    def __init__(self, headless: Optional[bool] = None):
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.current_page: Optional[Page] = None
        self.headless = headless if headless is not None else BROWSER_CONFIG["headless"]

    def start(self) -> Page:
        """Kalıcı profil ile resmi Chrome tarayıcısını başlatır."""
        logger.info("Tarayıcı başlatılıyor (Kalıcı profil: %s, Kanal: %s)...",
                    BROWSER_CONFIG["user_data_dir"], BROWSER_CONFIG["channel"])

        self.playwright = sync_playwright().start()
        
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=BROWSER_CONFIG["user_data_dir"],
            headless=self.headless,
            channel=BROWSER_CONFIG["channel"],
            no_viewport=True,
            args=BROWSER_CONFIG["args"],
            locale=BROWSER_CONFIG["locale"],
            timezone_id=BROWSER_CONFIG["timezone_id"]
        )

        # İlk açık sayfayı al veya yeni bir sayfa aç
        if len(self.context.pages) > 0:
            self.current_page = self.context.pages[0]
        else:
            self.current_page = self.context.new_page()

        logger.info("Tarayıcı ve bağlam başarıyla hazırlandı.")
        return self.current_page

    def navigate_warmup_flow(self) -> Page:
        """
        VFS'in doğrudan login engeline ve 'Session Expired' hatasına takılmamak için
        plan.md Bölüm 7'deki ısınma akışını tam sırasıyla izler:
        1. Ana portal sayfası (https://visa.vfsglobal.com/tur/en/bgr/)
        2. Çerez izinlerini kabul etme
        3. Randevu sayfası (book-an-appointment)
        4. Doğal kaydırma ve 'Book now' butonuna insan tıklaması
        5. Açılan login sayfasına geçiş
        """
        if not self.current_page:
            raise RuntimeError("Tarayıcı henüz başlatılmadı. Önce start() çağrılmalı.")

        page = self.current_page
        
        # 1. Randevu sayfası yükleniyor
        logger.info("Randevu tanıtım sayfası açılıyor (%s)...", APPOINTMENT_URL)
        page.goto(APPOINTMENT_URL, wait_until="domcontentloaded", timeout=60000)
        HumanTiming.sleep_jitter(2.0)
        self.handle_cookie_banner(page)

        # Doğal sayfa kaydırma
        logger.info("Sayfa insan gibi aşağı kaydırılıyor...")
        HumanScroll.scroll_smooth(page, pixels=350, steps=4)
        HumanTiming.sleep_jitter(1.2)

        # 'Book now' butonunu bul
        book_now_btn = page.locator("a:has-text('Book now'), button:has-text('Book now')").first
        if not book_now_btn.is_visible(timeout=5000):
            logger.warning("'Book now' butonu hemen görünmedi, sayfa biraz daha taranıyor...")
            page.evaluate("window.scrollBy({ top: 200, behavior: 'smooth' });")
            HumanTiming.sleep_jitter(1.0)

        logger.info("'Book now' butonuna insansı kavisle yaklaşılıyor ve tıklanıyor...")
        
        # 'Book now' hedefi _blank olduğu için yeni sayfayı yakala
        with self.context.expect_page() as page_info:
            HumanMouse.click_locator(page, book_now_btn)

        login_page = page_info.value
        login_page.wait_for_load_state("domcontentloaded")
        login_page.bring_to_front()
        self.current_page = login_page

        logger.info("Login sayfası başarıyla açıldı: %s", login_page.url)
        HumanTiming.sleep_jitter(2.0)

        # Eğer 'Session Expired' sayfası gelirse 'Sign In Again' veya 'Go back to home' bağlantısını tıkla
        if "session expired" in login_page.title().lower() or login_page.locator("text=Session Expired").count() > 0:
            logger.warning("Session Expired ekranı tespit edildi, 'Sign In Again' linki tıklanıyor...")
            retry_link = login_page.locator("a:has-text('Sign In Again'), a:has-text('Go back to home')").first
            if retry_link.is_visible(timeout=3000):
                HumanMouse.click_locator(login_page, retry_link)
                HumanTiming.sleep_jitter(3.0)

        return login_page

    def handle_cookie_banner(self, page: Page):
        """OneTrust çerez izni penceresi varsa insan gibi tıklar."""
        try:
            accept_btn = page.locator("#onetrust-accept-btn-handler")
            if accept_btn.is_visible(timeout=4000):
                logger.info("Çerez kabul uyarısı tespit edildi, insan gibi onaylanıyor...")
                HumanMouse.click_locator(page, accept_btn)
                HumanTiming.sleep_jitter(1.0)
            else:
                logger.debug("Çerez uyarısı görünmedi veya önceden onaylanmış.")
        except Exception as e:
            logger.debug("Çerez kontrolü hatasız tamamlandı (istisna: %s)", e)

    def take_screenshot(self, page: Page, name_prefix: str = "capture") -> Path:
        """Ekran görüntüsü alıp screenshots dizinine kaydeder."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name_prefix}_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        page.screenshot(path=str(filepath))
        logger.info("Ekran görüntüsü kaydedildi: %s", filepath)
        return filepath

    def stop(self):
        """Tarayıcı ve bağlamı güvenli bir şekilde kapatır."""
        logger.info("Tarayıcı kapatılıyor...")
        try:
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()
        except Exception as e:
            logger.warning("Tarayıcı kapatılırken hata: %s", e)
        logger.info("Tarayıcı kapatıldı.")
