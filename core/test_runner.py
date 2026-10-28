"""
core/test_runner.py - Adım Adım Canlı Test Yürütücüsü ve Durum Yöneticisi
Kullanıcı arayüzüne anlık durum, aşama ilerlemesi (pipeline) ve log telemetrisi sağlar.
"""
import time
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from config import SCREENSHOTS_DIR
from core.browser import BrowserManager
from core.captcha import TurnstileSolver
from core.session_manager import SessionManager
from core.human import HumanTiming

logger = logging.getLogger("VFS_Bot.TestRunner")

DEFAULT_STEPS = [
    {
        "id": 1,
        "title": "Tarayıcı & Kalıcı Profil Başlatma",
        "desc": "CDP izleri temizlenmiş Chrome ve kalıcı kullanıcı profili açılıyor.",
        "status": "pending",
        "details": "Beklemede"
    },
    {
        "id": 2,
        "title": "VFS Randevu Sayfası & Çerez İzinleri (Warm-up)",
        "desc": "Randevu tanıtım sayfası açılıyor, çerez uyarısı insan gibi onaylanıyor.",
        "status": "pending",
        "details": "Beklemede"
    },
    {
        "id": 3,
        "title": "İnsansı Kavisle 'Book now' Tıklaması",
        "desc": "Kübik Bézier eğrili fare hareketi ile 'Book now' butonuna basılıp Login sekmesi açılıyor.",
        "status": "pending",
        "details": "Beklemede"
    },
    {
        "id": 4,
        "title": "Cloudflare Turnstile Captcha Çözümü",
        "desc": "Cloudflare widget'ı taranıyor, koordinatlar hesaplanıp insan reaksiyonuyla onaylanıyor.",
        "status": "pending",
        "details": "Beklemede"
    },
    {
        "id": 5,
        "title": "Giriş Formu Teyidi & Oturum/Çerez Kaydı",
        "desc": "Email ve şifre formunun hazır olduğu doğrulanıyor, cf_clearance çerezleri diske kaydediliyor.",
        "status": "pending",
        "details": "Beklemede"
    }
]


class TestRunner:
    """Arayüz için tekil (singleton) test yöneticisi."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_running = False
        self.stop_requested = False
        self.status = "idle"  # idle, running, success, error, stopped
        self.steps = [dict(s) for s in DEFAULT_STEPS]
        self.logs: List[Dict[str, str]] = []
        self.latest_screenshot: Optional[str] = None
        self.browser_manager: Optional[BrowserManager] = None
        self._thread: Optional[threading.Thread] = None
        self.token: Optional[str] = None

    def reset(self):
        with self._lock:
            self.status = "idle"
            self.stop_requested = False
            self.steps = [dict(s) for s in DEFAULT_STEPS]
            self.token = None

    def add_log(self, level: str, message: str):
        now = datetime.now().strftime("%H:%M:%S")
        entry = {"time": now, "level": level, "msg": message}
        with self._lock:
            self.logs.append(entry)
            if len(self.logs) > 300:
                self.logs.pop(0)
        logger.info("[%s] %s", level, message)

    def set_step_status(self, step_id: int, status: str, details: str = ""):
        with self._lock:
            for s in self.steps:
                if s["id"] == step_id:
                    s["status"] = status
                    if details:
                        s["details"] = details
                    break

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_running": self.is_running,
                "status": self.status,
                "steps": [dict(s) for s in self.steps],
                "logs": list(self.logs),
                "latest_screenshot": self.latest_screenshot,
                "token_preview": (self.token[:20] + "...") if self.token else None
            }

    def start_test(self) -> bool:
        with self._lock:
            if self.is_running:
                return False
            self.is_running = True
            self.status = "running"
            self.stop_requested = False
            self.steps = [dict(s) for s in DEFAULT_STEPS]

        self.add_log("INFO", "=== Canlı Test Başlatıldı: Sayfa Açma & Captcha Çözümü ===")
        self._thread = threading.Thread(target=self._run_workflow, daemon=True)
        self._thread.start()
        return True

    def stop_test(self):
        with self._lock:
            self.stop_requested = True
        self.add_log("WARNING", "Durdurma talebi alındı, tarayıcı sonlandırılıyor...")
        if self.browser_manager:
            try:
                self.browser_manager.stop()
            except Exception:
                pass

    def _run_workflow(self):
        try:
            # ---------------- Adım 1: Tarayıcı Başlatma ----------------
            self.set_step_status(1, "running", "Tarayıcı ve kalıcı profil hazırlanıyor...")
            self.add_log("INFO", "[Adım 1/5] Chrome tarayıcısı ve kalıcı profil başlatılıyor...")
            
            self.browser_manager = BrowserManager(headless=False)
            page = self.browser_manager.start()
            
            self.set_step_status(1, "completed", "Chrome başarıyla başlatıldı.")
            self.add_log("SUCCESS", "[Adım 1/5] Tarayıcı ve kalıcı kullanıcı profili hazır.")

            if self.stop_requested:
                raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

            # ---------------- Adım 2: Isınma & Randevu Sayfası ----------------
            self.set_step_status(2, "running", "Randevu tanıtım sayfası açılıyor...")
            self.add_log("INFO", "[Adım 2/5] Isınma akışı: Randevu tanıtım sayfası yükleniyor...")
            
            from config import APPOINTMENT_URL
            page.goto(APPOINTMENT_URL, wait_until="domcontentloaded", timeout=60000)
            HumanTiming.sleep_jitter(2.0)
            
            self.browser_manager.handle_cookie_banner(page)
            
            self.set_step_status(2, "completed", "Randevu sayfası açıldı, çerezler kabul edildi.")
            self.add_log("SUCCESS", "[Adım 2/5] Randevu sayfası hazırlandı ve çerez uyarısı onaylandı.")

            if self.stop_requested:
                raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

            # ---------------- Adım 3: 'Book now' Butonuna Tıklama ----------------
            self.set_step_status(3, "running", "Sayfa kaydırılıyor ve 'Book now' butonuna yaklaşılıyor...")
            self.add_log("INFO", "[Adım 3/5] Doğal kaydırma ve 'Book now' butonuna insansı kavisle tıklanıyor...")
            
            from core.human import HumanScroll, HumanMouse
            HumanScroll.scroll_smooth(page, pixels=350, steps=4)
            HumanTiming.sleep_jitter(1.2)
            
            book_now_btn = page.locator("a:has-text('Book now'), button:has-text('Book now')").first
            if not book_now_btn.is_visible(timeout=5000):
                page.evaluate("window.scrollBy({ top: 200, behavior: 'smooth' });")
                HumanTiming.sleep_jitter(1.0)

            with self.browser_manager.context.expect_page() as page_info:
                HumanMouse.click_locator(page, book_now_btn)

            login_page = page_info.value
            login_page.wait_for_load_state("domcontentloaded")
            login_page.bring_to_front()
            self.browser_manager.current_page = login_page

            self.set_step_status(3, "completed", "Login sekmesi başarıyla açıldı.")
            self.add_log("SUCCESS", f"[Adım 3/5] Login sekmesine geçildi: {login_page.url}")

            if self.stop_requested:
                raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

            # ---------------- Adım 4: Cloudflare Turnstile Çözümü ----------------
            self.set_step_status(4, "running", "Turnstile captcha tespiti ve insansı onaylama...")
            self.add_log("INFO", "[Adım 4/5] Cloudflare Turnstile denetleniyor ve çözülüyor...")
            
            success, token = TurnstileSolver.solve(login_page, max_wait_sec=30)
            if not success:
                self.set_step_status(4, "failed", "Turnstile çözülemedi veya süre aşıldı.")
                self.add_log("ERROR", "[Adım 4/5] Turnstile doğrulanamadı!")
                # Ekran görüntüsü al
                sc_path = self.browser_manager.take_screenshot(login_page, name_prefix="failed_turnstile")
                self.latest_screenshot = sc_path.name
                raise RuntimeError("Turnstile çözülemedi")

            self.token = token
            self.set_step_status(4, "completed", f"Turnstile onaylandı! Token: {token[:18]}...")
            self.add_log("SUCCESS", f"[Adım 4/5] Turnstile başarıyla geçildi! Token: {token[:24]}...")

            if self.stop_requested:
                raise InterruptedError("İşlem kullanıcı tarafından durduruldu.")

            # ---------------- Adım 5: Giriş Formu & Çerez Kaydı ----------------
            self.set_step_status(5, "running", "Giriş formu teyit ediliyor ve oturum çerezleri saklanıyor...")
            self.add_log("INFO", "[Adım 5/5] Giriş form alanları doğrulanıyor...")
            
            HumanTiming.sleep_jitter(1.5)
            email_input = login_page.locator("input[type='email'], input[formcontrolname='username'], #mat-input-0").first
            is_form_ready = email_input.is_visible(timeout=5000)

            SessionManager.save_session(self.browser_manager.context, session_id="bgr_vfs")
            sc_path = self.browser_manager.take_screenshot(login_page, name_prefix="stage1_success")
            self.latest_screenshot = sc_path.name

            if is_form_ready:
                self.set_step_status(5, "completed", "Giriş formu hazır ve oturum çerezleri kaydedildi.")
                self.add_log("SUCCESS", "[Adım 5/5] Form (Email & Şifre) aktif ve hazır. Aşama 1 tamamlandı!")
            else:
                self.set_step_status(5, "completed", "Oturum çerezleri kaydedildi.")
                self.add_log("WARNING", "[Adım 5/5] Oturum kaydedildi ancak form öğesi henüz tam görünür değil.")

            with self._lock:
                self.status = "success"
            self.add_log("SUCCESS", "🎉 1. AŞAMA BAŞARIYLA TAMAMLANDI! Sayfa açıldı, Captcha geçildi.")

        except InterruptedError:
            with self._lock:
                self.status = "stopped"
            self.add_log("WARNING", "İşlem kullanıcı tarafından durduruldu.")
        except Exception as e:
            with self._lock:
                self.status = "error"
            self.add_log("ERROR", f"Hata meydana geldi: {str(e)}")
            logger.exception("Test Runner hatası:")
        finally:
            with self._lock:
                self.is_running = False
            # 5 saniye sonra tarayıcıyı kapat
            time.sleep(4.0)
            if self.browser_manager:
                try:
                    self.browser_manager.stop()
                except Exception:
                    pass


# Tekil örnek
runner_instance = TestRunner()
