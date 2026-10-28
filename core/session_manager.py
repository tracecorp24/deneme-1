"""
core/session_manager.py - Oturum ve Çerez Yönetimi
plan.md Bölüm 6 gereksinimlerine uygun olarak tarayıcı çerezlerini (cf_clearance, __cf_bm vb.)
ve yerel depolama verilerini diske yazar, gerektiğinde geri yükler.
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from patchright.sync_api import BrowserContext, Page

from core.config import SESSIONS_DIR

logger = logging.getLogger("VFS_Bot.Session")


class SessionManager:
    """Oturum çerezlerini diske atomik yazma ve yükleme yöneticisi."""

    @staticmethod
    def get_session_file(session_id: str = "default") -> Path:
        """Oturum dosyasının yolunu döndürür."""
        return SESSIONS_DIR / f"session_{session_id}.json"

    @classmethod
    def save_session(cls, context: BrowserContext, session_id: str = "default") -> bool:
        """
        Bağlamdaki tüm çerezleri ve cf_clearance bilgilerini diske kaydeder.
        """
        try:
            cookies = context.cookies()
            filepath = cls.get_session_file(session_id)
            temp_path = filepath.with_suffix(".tmp")

            data = {
                "session_id": session_id,
                "cookie_count": len(cookies),
                "cookies": cookies
            }

            # Atomik yazma (önce geçici dosyaya yaz, sonra değiştir)
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            temp_path.replace(filepath)
            logger.info("Oturum çerezleri başarıyla kaydedildi (%d çerez) -> %s", len(cookies), filepath.name)
            return True
        except Exception as e:
            logger.error("Oturum kaydedilirken hata oluştu: %s", e)
            return False

    @classmethod
    def load_session(cls, context: BrowserContext, session_id: str = "default") -> bool:
        """Kayıtlı çerezleri bağlama geri yükler."""
        filepath = cls.get_session_file(session_id)
        if not filepath.exists():
            logger.info("Önceden kaydedilmiş oturum dosyası bulunamadı: %s", filepath.name)
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            cookies = data.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
                logger.info("Kaydedilmiş %d çerez bağlama yüklendi.", len(cookies))
                return True
            return False
        except Exception as e:
            logger.warning("Oturum yüklenirken hata oluştu: %s", e)
            return False
