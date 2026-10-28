"""
bot/http.py - TLS parmak izi + Cloudflare kapısı. 403 burada yakalanır, çağırana sızmaz.
"""
from __future__ import annotations
import asyncio
import random
import time
from urllib.parse import urlparse
from typing import Any

from curl_cffi.requests import AsyncSession

from .config import CFG
from .db import DB
from .proxy import ProxyManager

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def split_proxy(proxy_url: str) -> dict[str, str] | None:
    """
    C1: user:pass@host:port proxy URL'sini Playwright uyumlu dict formatına böler.
    Örnek: http://user:pass@1.2.3.4:8080 -> {"server": "http://1.2.3.4:8080", "username": "user", "password": "pass"}
    """
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    scheme = p.scheme or "http"
    host = p.hostname or ""
    port = f":{p.port}" if p.port else ""
    server = f"{scheme}://{host}{port}"
    res: dict[str, str] = {"server": server}
    if p.username:
        res["username"] = p.username
    if p.password:
        res["password"] = p.password
    return res


class VfsHttp:
    """cf_clearance IP+UA'ya bağlı olduğu için: bir identity = bir (proxy, UA, cookie) üçlüsü."""

    def __init__(self, proxy_mgr: ProxyManager):
        self.proxy_mgr = proxy_mgr
        self._sessions: dict[str, AsyncSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, identity: str) -> asyncio.Lock:
        return self._locks.setdefault(identity, asyncio.Lock())

    async def _session(self, identity: str, proxy: str) -> AsyncSession:
        if identity in self._sessions:
            return self._sessions[identity]
        sess = AsyncSession(
            impersonate=CFG["http"]["impersonate"],
            timeout=float(CFG["http"]["timeout_s"]),
            proxies={"http": proxy, "https": proxy} if proxy else None,
        )
        self._sessions[identity] = sess
        return sess

    # ---------- Cloudflare ----------
    async def ensure_cf_clearance(self, identity: str, proxy: str) -> bool:
        """Geçerli cf_clearance yoksa gerçek Chrome ile üret. Datacenter IP'de işe yaramaz."""
        async with self._lock(identity):
            s = DB.session_load(identity)
            if s and s.get("cf_clearance") and (s.get("cf_expires_at") or 0) > time.time():
                return True
            cookie, ua = await self._mint_cf_clearance(proxy)
            # C4: Mint başarısızsa veya UA boşsa False dön
            if not cookie or not ua:
                DB.log("WARN", f"cf_clearance üretilemedi: {identity}")
                return False
            DB.session_save(
                identity,
                proxy_id=None,
                user_agent=ua,
                cf_clearance=cookie,
                cf_expires_at=time.time() + float(CFG["session"]["cf_clearance_ttl_s"]),
            )
            DB.log("INFO", f"cf_clearance tazelendi: {identity}")
            return True

    async def _mint_cf_clearance(self, proxy: str) -> tuple[str | None, str]:
        """
        Playwright'ın Chromium'u Cloudflare'de bloke → channel='chrome' şart.
        C1: split_proxy ile user:pass ayrımı.
        C2: headless CFG["http"]["headless"]'den gelir.
        C4: mint eden UA ile cf_clearance birebir saklanır; hata durumunda CHROME_UA'ya düşülmez.
        """
        from patchright.async_api import async_playwright

        headless = CFG["http"].get("headless", False)
        launch_kwargs: dict[str, Any] = {
            "channel": "chrome",
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"]
        }
        if proxy:
            parsed_proxy = split_proxy(proxy)
            if parsed_proxy:
                launch_kwargs["proxy"] = parsed_proxy

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_kwargs)
            ctx = await browser.new_context()
            page = await ctx.new_page()
            try:
                await page.goto(CFG["portal"]["base"], wait_until="domcontentloaded", timeout=45000)
                for _ in range(35):
                    cookies = await ctx.cookies()
                    hit = next((c for c in cookies if c["name"] == "cf_clearance"), None)
                    if hit:
                        ua = await page.evaluate("navigator.userAgent")
                        return hit["value"], ua
                    await asyncio.sleep(1)
                # C4: Mint başarısızsa sahte UA yerine boş dön
                return None, ""
            except Exception as e:
                DB.log("WARN", f"_mint_cf_clearance hatası: {e}")
                return None, ""
            finally:
                await ctx.close()
                await browser.close()

    # ---------- istek ----------
    async def request(
        self,
        method: str,
        url: str,
        *,
        identity: str = "public",
        json_body: dict | None = None,
        headers: dict | None = None,
        retries: int | None = None,
    ):
        proxy = self.proxy_mgr.healthy(identity)
        retries = retries if retries is not None else int(CFG["http"]["max_retries"])

        for attempt in range(retries):
            # C4: clearance sağlanamazsa hemen sonraki denemeye geç
            ok = await self.ensure_cf_clearance(identity, proxy)
            if not ok:
                await asyncio.sleep(1)
                continue

            s = await self._session(identity, proxy)
            sess = DB.session_load(identity) or {}

            # C4: cf_clearance'ı mint eden UA'yı al
            used_ua = sess.get("user_agent") or CHROME_UA

            h = {
                "accept": "application/json, text/plain, */*",
                "accept-language": "tr-TR,tr;q=0.9,en;q=0.8",
                "content-type": "application/json",
                "origin": CFG["portal"]["base"].rstrip("/"),
                "referer": CFG["portal"]["base"].rstrip("/") + "/",
                "user-agent": used_ua,
            }
            if sess.get("authorize"):
                h["authorize"] = sess["authorize"]
            if sess.get("cf_clearance"):
                s.cookies.set("cf_clearance", sess["cf_clearance"], domain=".vfsglobal.com")
            h.update(headers or {})

            # B2: x-auth-token TTL kontrolü (20 dakikadan eskiyse WARN logla)
            x_token_ts = DB.meta_get("x_token_ts")
            if x_token_ts:
                try:
                    age_seconds = time.time() - float(x_token_ts)
                    if age_seconds > 1200:
                        DB.log("WARN", f"x-auth-token 20 dakikadan eski ({int(age_seconds)} sn) - bayatlama riski!")
                except Exception:
                    pass

            async with self.proxy_mgr.slot(proxy):
                await asyncio.sleep(random.uniform(0.2, 1.2))
                try:
                    resp = await s.request(method, url, json=json_body, headers=h)
                except Exception as exc:
                    DB.log("WARN", f"{method} {url} ağ hatası: {exc}")
                    await asyncio.sleep(min(2 ** attempt + random.random(), 300))
                    continue

            code = resp.status_code

            if code == 200:
                self.proxy_mgr.mark_ok(proxy)
                self._persist_cookies(identity, s)
                return resp

            if code == 409:
                # Sunucu "Repeated Delay: N saniye bekle" diyor — harfiyen uy
                try:
                    wait = int(resp.json().get("code", 30))
                except Exception:
                    wait = 30
                wait += int(CFG["polling"]["delay_honor_margin_s"])
                DB.log("INFO", f"409 Repeated Delay → {wait}s bekleniyor")
                await asyncio.sleep(wait)
                continue

            if code in (403, 429):
                # cf_clearance bayatlamış olabilir → cookie'yi yak
                DB.session_save(identity, cf_clearance=None, cf_expires_at=0)
                self.proxy_mgr.penalize(proxy)

                # C3: Havuz boşsa bekleme tavanını 60s'ye indir; havuz doluysa sıradaki IP'ye geç
                if not self.proxy_mgr.pool:
                    wait = min(2 ** attempt * 5 + random.random() * 5, 60)
                else:
                    wait = min(2 ** attempt * 2 + random.random() * 2, 30)

                await asyncio.sleep(wait)
                proxy = self.proxy_mgr.healthy(identity)
                continue

            if code == 401 and sess.get("authorize"):
                DB.session_save(identity, authorize=None)  # JWT bayat → yeniden login
                return resp

            if 500 <= code < 600:
                await asyncio.sleep(min(2 ** attempt + random.random(), 300))
                continue

            return resp

        DB.log("ERROR", f"{method} {url} {retries} denemede başarısız")
        return None

    def _persist_cookies(self, identity: str, sess: AsyncSession) -> None:
        try:
            jar = [
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in sess.cookies.jar
            ]
            DB.session_save(identity, cookies=jar)
        except Exception:
            pass

    async def close(self) -> None:
        for s in self._sessions.values():
            try:
                await s.close()
            except Exception:
                pass
        self._sessions.clear()
