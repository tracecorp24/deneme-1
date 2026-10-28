"""
bot/otp.py - IMAP OTP köprüsü. Hedefli SEARCH — tüm kutuyu taramaz.
"""
from __future__ import annotations
import asyncio
import email
import imaplib
import re
import time
from email.header import decode_header

from .config import CFG
from .db import DB


def _decode(value: str) -> str:
    parts = decode_header(value or "")
    return "".join(p.decode(enc or "utf-8", "ignore") if isinstance(p, bytes) else str(p) for p, enc in parts)


class OtpBridge:
    def __init__(self, host: str, user: str, app_password: str):
        self.host = host or "imap.gmail.com"
        self.user = user
        self.password = app_password

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.host, int(CFG["otp"]["imap_port"]))
        conn.login(self.user, self.password)
        conn.select("INBOX", readonly=True)
        return conn

    def _search(self, conn: imaplib.IMAP4_SSL, since_ts: float) -> list[bytes]:
        since = time.strftime("%d-%b-%Y", time.localtime(since_ts))
        criteria = [f'(SINCE "{since}"']
        sender = CFG["otp"]["sender_filter"]
        if sender:
            criteria.append(f'FROM "{sender}"')
        subject_or = " OR ".join(f'SUBJECT "{s}"' for s in CFG["otp"]["subject_filter"])
        if subject_or:
            criteria.append(f"({subject_or})")
        query = " ".join(criteria) + ")"
        try:
            typ, data = conn.search(None, query)
            return data[0].split() if typ == "OK" and data and data[0] else []
        except Exception:
            # Yedek: basit arama
            typ, data = conn.search(None, f'(SINCE "{since}")')
            return data[0].split() if typ == "OK" and data and data[0] else []

    async def wait_for_otp(self, since_ts: float | None = None, timeout: float | None = None) -> str | None:
        """2 saniyede bir hedefli arama. 85 saniye içinde 6 haneli OTP kodunu yakalar."""
        since_ts = since_ts or (time.time() - 10)
        timeout = timeout or float(CFG["otp"]["otp_timeout_s"])
        deadline = time.time() + timeout
        seen: set[bytes] = set()
        conn = None

        try:
            conn = await asyncio.to_thread(self._connect)
            while time.time() < deadline:
                ids = await asyncio.to_thread(self._search, conn, since_ts)
                for msg_id in reversed(ids):
                    if msg_id in seen:
                        continue
                    seen.add(msg_id)
                    typ, raw = await asyncio.to_thread(conn.fetch, msg_id, "(RFC822)")
                    if typ != "OK" or not raw or not raw[0]:
                        continue
                    msg = email.message_from_bytes(raw[0][1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += _decode(part.get_payload(decode=True).decode("utf-8", "ignore"))
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = _decode(payload.decode("utf-8", "ignore"))
                    text = f"{_decode(msg.get('Subject', ''))} {body}"
                    otp = re.search(CFG["otp"]["regex"], text)
                    if otp:
                        DB.log("INFO", f"OTP yakalandı: {otp.group(1)}")
                        return otp.group(1)
                await asyncio.sleep(float(CFG["otp"]["poll_interval_s"]))
            DB.log("WARN", f"OTP {timeout:.0f}s içinde gelmedi")
            return None
        except Exception as e:
            DB.log("ERROR", f"IMAP bağlantı/arama hatası: {e}")
            return None
        finally:
            if conn:
                try:
                    await asyncio.to_thread(conn.logout)
                except Exception:
                    pass

    @classmethod
    def test_connection(cls, host: str, user: str, password: str, port: int = 993) -> tuple[bool, str]:
        """Test IMAP credentials and inbox connection synchronously."""
        if not user or not password:
            return False, "E-posta veya uygulama şifresi boş olamaz."
        try:
            conn = imaplib.IMAP4_SSL(host or "imap.gmail.com", port)
            conn.login(user, password)
            status, counts = conn.select("INBOX", readonly=True)
            msg_count = counts[0].decode() if counts and counts[0] else "0"
            conn.logout()
            return True, f"IMAP bağlantısı başarılı! Gelen kutusu doğrulandı ({msg_count} e-posta)."
        except imaplib.IMAP4.error as imap_err:
            return False, f"IMAP Kimlik Doğrulama Hatası: {str(imap_err)} (Gmail kullanıyorsanız 2 adımlı doğrulama 'Uygulama Şifresi' giriniz)."
        except Exception as e:
            return False, f"IMAP Bağlantı Hatası: {str(e)}"
